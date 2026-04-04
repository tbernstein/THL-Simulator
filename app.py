import streamlit as st
import csv
import itertools
import random
import statistics
import pandas as pd
from collections import defaultdict

# --- CONFIG ---
st.set_page_config(page_title="THL Strategy Command V15", layout="wide")

def get_class_from_deck(deck_name):
    return deck_name.split()[-1]

def get_weighted_classes(classes, class_weights, k=4):
    chosen = set()
    while len(chosen) < k:
        weights = [class_weights.get(c, 1.0) for c in classes]
        if sum(weights) == 0: weights = [1.0] * len(classes)
        pick = random.choices(classes, weights=weights, k=1)[0]
        chosen.add(pick)
    return list(chosen)

def get_archetype_prob(deck_name, arch_weights):
    return arch_weights.get(deck_name, 1.0)

def simulate_conquest_bo5(my_decks, opp_decks, win_rates, iterations=150):
    wins = 0
    rng = random.Random()
    rng.seed("".join(my_decks) + "".join(opp_decks))
    
    for _ in range(iterations):
        my_rem, opp_rem = list(my_decks), list(opp_decks)
        while my_rem and opp_rem:
            my_p, opp_p = rng.choice(my_rem), rng.choice(opp_rem)
            wr = win_rates.get(my_p, {}).get(opp_p, 0.5)
            if rng.random() < wr: my_rem.remove(my_p)
            else: opp_rem.remove(opp_p)
        if not my_rem: wins += 1
    return (wins / iterations) * 100

# Fictitious Play Algorithm to find Game Theory Nash Equilibrium
def get_nash_equilibrium(payoff_matrix, iterations=5000):
    my_decks = list(payoff_matrix.keys())
    if not my_decks: return {}
    opp_decks = list(payoff_matrix[my_decks[0]].keys())
    if not opp_decks: return {d: 100.0 for d in my_decks}
    
    my_counts = {d: 0 for d in my_decks}
    opp_counts = {d: 0 for d in opp_decks}
    
    for _ in range(iterations):
        # Best response for Me
        best_my = max(my_decks, key=lambda md: sum(payoff_matrix[md][od] * opp_counts[od] for od in opp_decks) / max(1, sum(opp_counts.values())))
        # Best response for Opponent (They want to minimize my EV)
        best_opp = min(opp_decks, key=lambda od: sum(payoff_matrix[md][od] * my_counts[md] for md in my_decks) / max(1, sum(my_counts.values())))
        
        my_counts[best_my] += 1
        opp_counts[best_opp] += 1
        
    total = sum(my_counts.values())
    return {d: (c / total) * 100 for d, c in my_counts.items() if c > 0}

# --- vS DATA LOADERS ---
def load_vs_matchups(uploaded_file):
    win_rates, archetypes = {}, []
    content = uploaded_file.getvalue().decode('utf-8-sig').splitlines()
    reader = list(csv.reader(content))
    
    header_row = None
    for row in reader:
        if len(row) > 5 and row[0].strip() == '':
            header_row = row
            break
            
    if not header_row: return {}, []
    
    archetypes = [h.strip() for h in header_row[1:] if h.strip()]
    
    for row in reader:
        if not row or not row[0].strip() or row == header_row: continue
        my_d = row[0].strip()
        win_rates[my_d] = {}
        for i, opp_deck in enumerate(archetypes):
            try: win_rates[my_d][opp_deck] = float(row[i+1])
            except: win_rates[my_d][opp_deck] = 0.5
    return win_rates, archetypes

def load_vs_frequencies(uploaded_file):
    freqs = {}
    content = uploaded_file.getvalue().decode('utf-8-sig').splitlines()
    reader = csv.reader(content)
    
    header_row = None
    for row in reader:
        if row and row[0].strip() == 'Rank':
            header_row = [c.strip() for c in row]
            break
            
    if not header_row: return {}
    
    try: l_index = header_row.index('L')
    except ValueError: return {}
        
    for row in reader:
        if not row or not row[0].strip() or row == header_row: continue
        name = row[0].strip()
        try: freqs[name] = float(row[l_index])
        except: pass
    return freqs

# --- UI ---
st.title("🛡️ THL Strategist: Legacy Division")

st.sidebar.header("vS Raw Data Uploads")
matchup_file = st.sidebar.file_uploader("1. Matchup Table (.csv)", type=['csv'])
class_file = st.sidebar.file_uploader("2. Class Frequency (.csv)", type=['csv'])
deck_file = st.sidebar.file_uploader("3. Deck Frequency (.csv)", type=['csv'])

if matchup_file:
    win_rates, archetypes = load_vs_matchups(matchup_file)
    class_map = defaultdict(list)
    for d in archetypes: class_map[get_class_from_deck(d)].append(d)
    all_classes = list(class_map.keys())
    
    class_weights = {}
    arch_weights = {}
    
    if class_file and deck_file:
        raw_class_freqs = load_vs_frequencies(class_file)
        raw_deck_freqs = load_vs_frequencies(deck_file)
        class_weights = raw_class_freqs
        
        for cls, decks in class_map.items():
            total_cls_freq = sum(raw_deck_freqs.get(d, 0.0) for d in decks)
            for d in decks:
                if total_cls_freq > 0: arch_weights[d] = raw_deck_freqs.get(d, 0.0) / total_cls_freq
                else: arch_weights[d] = 1.0 / len(decks)

    phase = st.sidebar.selectbox("Workflow Step", [
        "Phase 1: Lineup Builder (Find Classes)", 
        "Phase 2: Archetype Optimizer (Find Decks)", 
        "Phase 3: Match Day Strategy (Ban Matrix & Nash)",
        "Phase 4: Fog of War Tracker"
    ])

    # --- PHASE 1: LINEUP BUILDER ---
    if phase == "Phase 1: Lineup Builder (Find Classes)":
        st.header("Phase 1: Pre-Lock Class Optimization")
        
        if st.button("Find Best 4 Classes to Lock (Takes ~10 sec)"):
            with st.spinner('Running Monte Carlo simulations against the overall meta...'):
                class_combos = list(itertools.combinations(all_classes, 4))
                
                meta_field = []
                for _ in range(100):
                    opp_classes = get_weighted_classes(all_classes, class_weights, 4)
                    opp_decks = []
                    for c in opp_classes:
                        options = class_map[c]
                        best_d = max(options, key=lambda d: get_archetype_prob(d, arch_weights))
                        opp_decks.append(best_d)
                    meta_field.append(opp_decks)

                all_results = []

                for my_class_combo in class_combos:
                    my_archetype_lists = [class_map[c] for c in my_class_combo]
                    
                    matchup_wrs = []
                    
                    for opp_decks in meta_field:
                        best_post_reveal_wr = 0
                        for my_deck_combo in itertools.product(*my_archetype_lists):
                            wr = simulate_conquest_bo5(random.sample(list(my_deck_combo), 3), random.sample(opp_decks, 3), win_rates, iterations=100)
                            if wr > best_post_reveal_wr: best_post_reveal_wr = wr
                        matchup_wrs.append(best_post_reveal_wr)
                    
                    avg_wr = statistics.mean(matchup_wrs)
                    floor_wr = min(matchup_wrs)
                    ceiling_wr = max(matchup_wrs)
                    std_dev = statistics.stdev(matchup_wrs) if len(matchup_wrs) > 1 else 0.0
                    favored_pct = sum(1 for w in matchup_wrs if w > 50.0) / len(matchup_wrs) * 100
                    
                    all_results.append({
                        "Lineup": ", ".join(my_class_combo),
                        "Expected WR": avg_wr,
                        "Floor": floor_wr,
                        "Ceiling": ceiling_wr,
                        "Std Dev": std_dev,
                        "Favored %": favored_pct
                    })

                all_results = sorted(all_results, key=lambda x: x["Expected WR"], reverse=True)
                best_lineup = all_results[0]
                top_wr = best_lineup['Expected WR']
                
                st.success(f"### 🏆 Absolute Peak Lineup: {best_lineup['Lineup']} ({top_wr:.2f}%)")
                st.write("---")
                
                with st.expander("📖 How to Read the Advanced Metrics", expanded=False):
                    st.markdown("""
                    **In Conquest, average win rate isn't everything. Use these metrics to pick a lineup that matches your risk tolerance:**
                    * **Expected WR (Mean):** Your overall average win probability against the expected meta.
                    * **The Floor (Min):** Your absolute worst-case scenario. A high floor means the lineup is safe and hard to sweep.
                    * **The Ceiling (Max):** Your absolute best-case scenario. High ceilings indicate you hard-counter specific popular decks.
                    * **Volatility (Std Dev):** How much your win rate swings from matchup to matchup. Lower means 50/50, skill-testing games. Higher means polarizing, rock-paper-scissors games.
                    * **% Favored:** The percentage of meta lineups where you have a >50% chance to win. Often more important than the raw Expected WR!
                    """)
                
                st.header("📊 Categorized Analytics Leaderboard")
                
                zones = {
                    "🟩 The 'Margin of Error' Zone (< 0.5% Delta)": [],
                    "🟨 The 'Tiebreaker' Zone (0.5% - 1.5% Delta)": [],
                    "🟧 The 'Meaningful Edge' Zone (1.5% - 3.0% Delta)": [],
                    "🟥 The 'Hard Counter' Zone (> 3.0% Delta)": []
                }
                
                for i, r in enumerate(all_results):
                    delta = top_wr - r["Expected WR"]
                    row_data = {
                        "Rank": i + 1,
                        "Classes": r["Lineup"],
                        "Expected WR": f"{r['Expected WR']:.1f}%",
                        "Floor (Min)": f"{r['Floor']:.1f}%",
                        "Ceiling (Max)": f"{r['Ceiling']:.1f}%",
                        "Volatility": f"±{r['Std Dev']:.1f}%",
                        "% Favored": f"{r['Favored %']:.1f}%",
                        "Delta to #1": f"-{delta:.2f}%"
                    }
                    
                    if delta < 0.5: zones["🟩 The 'Margin of Error' Zone (< 0.5% Delta)"].append(row_data)
                    elif delta < 1.5: zones["🟨 The 'Tiebreaker' Zone (0.5% - 1.5% Delta)"].append(row_data)
                    elif delta < 3.0: zones["🟧 The 'Meaningful Edge' Zone (1.5% - 3.0% Delta)"].append(row_data)
                    else: zones["🟥 The 'Hard Counter' Zone (> 3.0% Delta)"].append(row_data)

                for zone_name, rows in zones.items():
                    if rows:
                        st.subheader(zone_name)
                        st.dataframe(rows, use_container_width=True, hide_index=True)

    # --- PHASE 2: ARCHETYPE OPTIMIZER ---
    elif phase == "Phase 2: Archetype Optimizer (Find Decks)":
        st.header("Phase 2: Archetype Optimizer")
        
        col1, col2 = st.columns(2)
        with col1: my_classes = st.multiselect("Your 4 Locked Classes:", all_classes, max_selections=4)
        with col2: opp_classes = st.multiselect("Opponent's 4 Revealed Classes:", all_classes, max_selections=4)

        if len(my_classes) == 4 and len(opp_classes) == 4:
            if st.button("Find Best Archetypes"):
                with st.spinner("Simulating archetype combinations against their specific classes..."):
                    opp_combos = list(itertools.product(*[class_map[c] for c in opp_classes]))
                    my_combos = list(itertools.product(*[class_map[c] for c in my_classes]))

                    opp_probs = []
                    for o_c in opp_combos:
                        p = 1.0
                        for d in o_c: p *= get_archetype_prob(d, arch_weights)
                        opp_probs.append(p)
                    total_p = sum(opp_probs)
                    if total_p > 0: opp_probs = [p / total_p for p in opp_probs]
                    else: opp_probs = [1.0 / len(opp_combos)] * len(opp_combos)

                    best_wr = -1
                    best_lineup = []
                    
                    progress_bar = st.progress(0)
                    total_my_combos = len(my_combos)

                    for i, my_4 in enumerate(my_combos):
                        expected_wr = 0
                        for opp_4, prob in zip(opp_combos, opp_probs):
                            my_ban = min(opp_4, key=lambda od: sum(win_rates.get(md, {}).get(od, 0.5) for md in my_4))
                            opp_ban = max(my_4, key=lambda md: sum(win_rates.get(md, {}).get(od, 0.5) for od in opp_4))

                            my_3 = [d for d in my_4 if d != opp_ban]
                            opp_3 = [d for d in opp_4 if d != my_ban]

                            wr = simulate_conquest_bo5(my_3, opp_3, win_rates, iterations=150)
                            expected_wr += wr * prob

                        if expected_wr > best_wr:
                            best_wr = expected_wr
                            best_lineup = my_4
                            
                        if i % max(1, total_my_combos // 10) == 0:
                            progress_bar.progress(min(1.0, i / total_my_combos))

                    progress_bar.empty()
                    st.success(f"### Optimal Archetypes to Build (Targeted WR: {best_wr:.2f}%)")
                    for d in best_lineup:
                        st.write(f"- **{d}**")

    # --- PHASE 3: MATCH DAY STRATEGY ---
    elif phase == "Phase 3: Match Day Strategy (Ban Matrix & Nash)":
        st.header("Phase 3: Match Day Ban Optimizer")
        
        col1, col2 = st.columns(2)
        with col1: my_classes = st.multiselect("Your 4 Classes:", all_classes, max_selections=4)
        with col2: opp_classes = st.multiselect("Opponent's 4 Classes:", all_classes, max_selections=4)

        if len(my_classes) == 4 and len(opp_classes) == 4:
            st.write("---")
            st.write("### Confirm Your Specific Archetypes")
            my_lineup = []
            arch_cols = st.columns(4)
            for i, c in enumerate(my_classes):
                with arch_cols[i]:
                    selected_deck = st.selectbox(f"Your {c}:", class_map[c])
                    my_lineup.append(selected_deck)
            
            st.write("---")
            if st.button("Generate Ban Matrix & Strategy"):
                with st.spinner("Calculating the Game Theory Nash Equilibrium for all Ban Scenarios..."):
                    # Generate the combinations for the opponent
                    opp_combos = list(itertools.product(*[class_map[c] for c in opp_classes]))
                    
                    # Store the EV for the Pandas Heatmap DataFrame
                    ban_matrix_data = {}
                    
                    worst_case_wr_overall = 101
                    best_my_ban_overall = None
                    optimal_leads_payoff = None
                    
                    for my_ban in my_lineup:
                        ban_matrix_data[my_ban] = {}
                        my_rem = [d for d in my_lineup if d != my_ban]
                        
                        expected_wr_for_my_ban = 0
                        total_prob_for_my_ban = 0
                        
                        for opp_ban_c in opp_classes:
                            rem_classes = [c for c in opp_classes if c != opp_ban_c]
                            opp_combos_filtered = list(itertools.product(*[class_map[c] for c in rem_classes]))
                            
                            expected_wr = 0
                            total_prob = 0
                            
                            for opp_combo in opp_combos_filtered:
                                prob = 1.0
                                for d in opp_combo: prob *= get_archetype_prob(d, arch_weights)
                                total_prob += prob
                                
                                wr = simulate_conquest_bo5(my_rem, list(opp_combo), win_rates, iterations=1500)
                                expected_wr += (wr * prob)
                                
                            ev_for_this_ban_pair = expected_wr / total_prob if total_prob > 0 else expected_wr
                            # Store for DataFrame (Columns = Opp Ban, Rows = My Ban)
                            ban_matrix_data[my_ban][f"Opp Bans {opp_ban_c}"] = round(ev_for_this_ban_pair, 2)
                            
                            # Heuristic for my worst-case scenario (Assuming opp bans perfectly against me)
                            if ev_for_this_ban_pair < worst_case_wr_overall:
                                worst_case_wr_overall = ev_for_this_ban_pair
                                best_my_ban_overall = my_ban
                                
                                # Generate the Game Theory Lead matrix for this optimal ban
                                optimal_leads_payoff = {md: {oc: 0 for oc in rem_classes} for md in my_rem}
                                for md in my_rem:
                                    for oc in rem_classes:
                                        ev_lead = 0
                                        lead_prob = 0
                                        for od in class_map[oc]:
                                            p = get_archetype_prob(od, arch_weights)
                                            ev_lead += win_rates.get(md, {}).get(od, 0.5) * p
                                            lead_prob += p
                                        optimal_leads_payoff[md][oc] = ev_lead / lead_prob if lead_prob > 0 else ev_lead
                
                st.success(f"### 🛑 Mathematically Optimal Ban: {best_my_ban_overall}")
                
                # --- NEW FEATURE 1: NASH EQUILIBRIUM MIXED QUEUE ---
                nash_strategy = get_nash_equilibrium(optimal_leads_payoff)
                
                st.info("### 🎲 Game 1 Nash Equilibrium (Unexploitable Lead)")
                st.write("To prevent your opponent from predicting your lead, roll a die or use a random number generator and queue your decks according to these exact probabilities:")
                for deck, pct in sorted(nash_strategy.items(), key=lambda x: x[1], reverse=True):
                    st.write(f"- **{deck}:** {pct:.1f}%")
                
                st.write("---")
                
                # --- NEW FEATURE 2: THE BAN HEAT MAP MATRIX ---
                st.subheader("🗺️ The Complete Ban Matrix")
                st.write("Rows are **Your Bans**, Columns are **Their Bans**. The numbers are your Expected Series Win Rate.")
                
                df_matrix = pd.DataFrame(ban_matrix_data).T
                # Apply a red-yellow-green background gradient. High numbers = Green.
                styled_df = df_matrix.style.background_gradient(cmap='RdYlGn', axis=None, vmin=df_matrix.values.min(), vmax=df_matrix.values.max())
                st.dataframe(styled_df, use_container_width=True)
                st.caption("If the Optimal Ban forces you to play against a deck you hate, look at the grid above to find a slightly mathematically inferior ban that gives you a better comfort matchup.")

    # --- PHASE 4: FOG OF WAR TRACKER ---
    elif phase == "Phase 4: Fog of War Tracker":
        st.header("Phase 4: Fog of War Tracker")
        
        if 'match_active' not in st.session_state: st.session_state.match_active = False
        
        if not st.session_state.match_active:
            col1, col2 = st.columns(2)
            with col1: my_u_classes = st.multiselect("Your 3 Unbanned Classes", all_classes, max_selections=3)
            with col2: opp_u_classes = st.multiselect("Opponent's 3 Unbanned Classes", all_classes, max_selections=3)
            
            if len(my_u_classes) == 3 and len(opp_u_classes) == 3:
                st.write("---")
                st.write("### Confirm Your Unbanned Archetypes")
                my_u = []
                arch_cols = st.columns(3)
                for i, c in enumerate(my_u_classes):
                    with arch_cols[i]:
                        selected_deck = st.selectbox(f"Your {c}:", class_map[c], key=f"p4_my_{c}")
                        my_u.append(selected_deck)

                st.write("---")
                if st.button("Initialize Match"):
                    st.session_state.my_rem = my_u
                    st.session_state.opp_status = {c: "Unknown" for c in opp_u_classes}
                    st.session_state.history = []
                    st.session_state.match_active = True
                    st.rerun()
        else:
            col1, col2 = st.columns(2)
            with col1: 
                st.subheader("Your Decks Left:")
                for d in st.session_state.my_rem:
                    st.write(f"- **{d}**")
            with col2: 
                st.subheader("Opponent Status:")
                for c, d in st.session_state.opp_status.items():
                    st.write(f"- {c}: **{d}**")
            
            if not st.session_state.my_rem:
                st.success("🎉 YOU WON! Report the score in Discord.")
                if st.button("Reset Tracker"): st.session_state.match_active = False; st.rerun()
            elif not st.session_state.opp_status:
                st.error("💀 You lost. Save your screenshots.")
                if st.button("Reset Tracker"): st.session_state.match_active = False; st.rerun()
            else:
                st.write("---")
                st.write("### 🔍 Reveal Opponent Archetype")
                reveal_c = st.selectbox("If they played an unknown deck, log it here:", [c for c, d in st.session_state.opp_status.items() if d == "Unknown"])
                if reveal_c:
                    reveal_d = st.selectbox(f"What {reveal_c} deck was it?", ["Off Meta"] + class_map[reveal_c])
                    if st.button("Lock Archetype"):
                        st.session_state.opp_status[reveal_c] = reveal_d
                        st.rerun()

                st.write("---")
                
                # --- NEW FEATURE: LIVE NASH EQUILIBRIUM FOR NEXT GAME ---
                live_payoff_matrix = {md: {oc: 0 for oc in st.session_state.opp_status.keys()} for md in st.session_state.my_rem}
                
                for my_deck in st.session_state.my_rem:
                    for opp_c, opp_d in st.session_state.opp_status.items():
                        if opp_d == "Off Meta":
                            c_decks = class_map[opp_c]
                            if c_decks:
                                mu = sum(win_rates.get(my_deck, {}).get(d, 0.5) for d in c_decks) / len(c_decks)
                            else:
                                mu = 0.5
                        elif opp_d != "Unknown":
                            mu = win_rates.get(my_deck, {}).get(opp_d, 0.5)
                        else:
                            ev = 0; p_total = 0
                            for possible_d in class_map[opp_c]:
                                p = get_archetype_prob(possible_d, arch_weights)
                                ev += win_rates.get(my_deck, {}).get(possible_d, 0.5) * p
                                p_total += p
                            mu = ev / p_total if p_total > 0 else ev
                            
                        live_payoff_matrix[my_deck][opp_c] = mu
                        
                live_nash_strategy = get_nash_equilibrium(live_payoff_matrix)
                
                st.info("### 🎲 Optimal Next-Game Queue (Nash Equilibrium)")
                st.write("To remain mathematically unexploitable this round, queue your decks using these exact probabilities:")
                for deck, pct in sorted(live_nash_strategy.items(), key=lambda x: x[1], reverse=True):
                    st.write(f"- **{deck}:** {pct:.1f}%")

                st.write("---")
                st.write("### ⚔️ Resolve Game")
                
                r_col1, r_col2 = st.columns(2)
                with r_col1:
                    my_played = st.selectbox("Deck you played:", st.session_state.my_rem)
                with r_col2:
                    opp_played_c = st.selectbox("Opponent class played:", list(st.session_state.opp_status.keys()))
                
                opp_d = st.session_state.opp_status[opp_played_c]
                opp_name = opp_d if opp_d != "Unknown" else f"Unknown {opp_played_c}"
                
                btn_col1, btn_col2 = st.columns(2)
                with btn_col1:
                    if st.button("I Won"):
                        st.session_state.history.append(f"🟢 **WIN:** {my_played} vs {opp_name}")
                        st.session_state.my_rem.remove(my_played)
                        st.rerun()
                with btn_col2:
                    if opp_d == "Unknown":
                        st.warning("⚠️ Reveal their exact archetype above before you log their win.")
                    else:
                        if st.button("They Won"):
                            st.session_state.history.append(f"🔴 **LOSS:** {my_played} vs {opp_name}")
                            del st.session_state.opp_status[opp_played_c]
                            st.rerun()
                            
            if st.session_state.get('history'):
                st.write("---")
                if not st.session_state.my_rem or not st.session_state.opp_status:
                    st.write("### 📜 Final Match Summary")
                else:
                    st.write("### 📜 Match History")
                    
                for i, game_log in enumerate(st.session_state.history):
                    st.write(f"**Game {i+1}:** {game_log}")
