import streamlit as st
import csv
import itertools
import random
import statistics
import pandas as pd
import io
from collections import defaultdict

# --- CONFIG ---
st.set_page_config(page_title="THL Strategy Command V27", layout="wide")

# --- CORE MATH & NASH SOLVERS ---
def solve_zero_sum(matrix, iterations=2500):
    """
    Fictitious play algorithm to solve zero-sum games (Nash Equilibrium).
    Row player maximizes, Col player minimizes.
    """
    rows = len(matrix)
    cols = len(matrix[0])

    if rows == 1 and cols == 1:
        return [1.0], [1.0], matrix[0][0]
    if rows == 1:
        best_col = matrix[0].index(min(matrix[0]))
        return [1.0], [1.0 if i == best_col else 0.0 for i in range(cols)], matrix[0][best_col]
    if cols == 1:
        best_row = [m[0] for m in matrix].index(max([m[0] for m in matrix]))
        return [1.0 if i == best_row else 0.0 for i in range(rows)], [1.0], matrix[best_row][0]

    row_cum = [0.0] * rows
    col_cum = [0.0] * cols
    row_plays = [0] * rows
    col_plays = [0] * cols

    r = random.randint(0, rows - 1)
    c = random.randint(0, cols - 1)

    for _ in range(iterations):
        row_plays[r] += 1
        col_plays[c] += 1

        for i in range(rows):
            row_cum[i] += matrix[i][c]
        for j in range(cols):
            col_cum[j] += matrix[r][j]

        # Row wants to maximize
        r = row_cum.index(max(row_cum))
        # Col wants to minimize
        c = col_cum.index(min(col_cum))

    v_upper = max(row_cum) / iterations
    v_lower = min(col_cum) / iterations
    return [p / iterations for p in row_plays], [p / iterations for p in col_plays], (v_upper + v_lower) / 2.0

def get_nash_queue(my_rem, opp_rem, win_rates, memo):
    """Recursively calculates the exact Conquest BO5 win rate and Queueing Nash Equilibrium."""
    state = (tuple(sorted(my_rem)), tuple(sorted(opp_rem)))
    if state in memo:
        return memo[state]
    
    if not my_rem: return 1.0, [], []
    if not opp_rem: return 0.0, [], []

    matrix = []
    for m_deck in my_rem:
        row = []
        for o_deck in opp_rem:
            wr = win_rates.get(m_deck, {}).get(o_deck, 0.5)
            # If I win, my deck is removed
            v_win, _, _ = get_nash_queue([d for d in my_rem if d != m_deck], opp_rem, win_rates, memo)
            # If I lose, opp deck is removed
            v_lose, _, _ = get_nash_queue(my_rem, [d for d in opp_rem if d != o_deck], win_rates, memo)
            row.append(wr * v_win + (1 - wr) * v_lose)
        matrix.append(row)

    my_p, opp_p, val = solve_zero_sum(matrix)
    memo[state] = (val, my_p, opp_p)
    return val, my_p, opp_p

def get_ban_matrix(my_4, opp_4, win_rates, memo):
    """Generates the 4x4 Ban Matrix to find optimal bans and BO5 Win Rate."""
    # Row: I choose what to ban from Opp. (Maximize)
    # Col: Opp chooses what to ban from Me. (Minimize)
    ban_matrix = []
    for my_ban in opp_4:
        row = []
        opp_3 = [d for d in opp_4 if d != my_ban]
        for opp_ban in my_4:
            my_3 = [d for d in my_4 if d != opp_ban]
            val, _, _ = get_nash_queue(my_3, opp_3, win_rates, memo)
            row.append(val)
        ban_matrix.append(row)
    return ban_matrix

# --- HELPER FUNCTIONS ---
def get_class_from_deck(deck_name):
    return str(deck_name).split()[-1]

def get_weighted_classes(classes, class_weights, k=4):
    chosen = set()
    while len(chosen) < k:
        weights = [class_weights.get(c, 1.0) for c in classes]
        if sum(weights) == 0: weights = [1.0] * len(classes)
        pick = random.choices(classes, weights=weights, k=1)[0]
        chosen.add(pick)
    return list(chosen)

def simulate_conquest_bo5(my_decks, opp_decks, win_rates, iterations=150):
    # Fast Monte Carlo used only for the broad field simulations in Phase 1
    wins = 0
    rng = random.Random()
    for _ in range(iterations):
        my_rem, opp_rem = list(my_decks), list(opp_decks)
        while my_rem and opp_rem:
            my_p, opp_p = rng.choice(my_rem), rng.choice(opp_rem)
            wr = win_rates.get(my_p, {}).get(opp_p, 0.5)
            if rng.random() < wr:
                my_rem.remove(my_p)
            else:
                opp_rem.remove(opp_p)
        if not my_rem:
            wins += 1
    return (wins / iterations) * 100

def apply_mastery_adjustments(win_rates, df_mastery):
    if df_mastery is None or df_mastery.empty:
        return win_rates, []

    # Nohands Gamer 4-Tier Scale Modifiers
    tier_modifiers = {
        'S': 0.045,  # 250+ games: Max edge
        'A': 0.015,  # 100-250 games: Solid edge
        'B': -0.035, # 50-100 games: Below vS baseline
        'C': -0.10   # <50 games: Severe penalty (Do not bring)
    }
    
    adjustment_logs = []

    for index, row in df_mastery.iterrows():
        try:
            deck_name = str(row.iloc[0]).strip()
            tier = str(row.iloc[1]).strip().upper()
        except (ValueError, TypeError, IndexError):
            continue

        if tier in tier_modifiers:
            modifier = tier_modifiers[tier]
            if deck_name in win_rates:
                for opp_deck in win_rates[deck_name]:
                    new_wr = win_rates[deck_name][opp_deck] + modifier
                    win_rates[deck_name][opp_deck] = max(0.05, min(0.95, new_wr))
                if modifier != 0:
                    adjustment_logs.append(f"**{deck_name}** (Tier {tier}): Adjusted expected WR by {modifier*100:+.1f}%")
                    
    return win_rates, adjustment_logs

# --- SIDEBAR UI: FILE UPLOADS ---
st.sidebar.header("📁 Step 1: Upload Data")

st.sidebar.markdown("**1. Matchup Table** *Optimized for download from vS Gold. Rows are your decks, columns are opponents.*")
file_matchups = st.sidebar.file_uploader("Upload Matchup Table", type=['csv'], key="m_up")

st.sidebar.markdown("**2. Deck Frequency** *Contains the popularity of specific deck archetypes from vS Gold.*")
file_deck_freq = st.sidebar.file_uploader("Upload Deck Frequency", type=['csv'], key="d_freq")

st.sidebar.markdown("**3. Class Frequency** *Contains the overall popularity of each class from vS Gold.*")
file_class_freq = st.sidebar.file_uploader("Upload Class Frequency", type=['csv'], key="c_freq")

st.sidebar.markdown("""
**4. Mastery Data (Optional)** *Adjusts win rates based on the Nohands Gamer mastery scale.*
**Format:** 2 columns (`Deck Name`, `Tier`)
* **S:** 250+ games (+4.5% WR)
* **A:** 100-250 games (+1.5% WR)
* **B:** 50-100 games (-3.5% WR)
* **C:** <50 games (-10.0% WR)
""")
file_mastery = st.sidebar.file_uploader("Upload Mastery CSV", type=['csv'], key="mastery")

# --- DATA PROCESSING ---
if file_matchups and file_deck_freq and file_class_freq:
    
    content_matchups = file_matchups.getvalue().decode('utf-8-sig')
    reader_m = list(csv.reader(io.StringIO(content_matchups)))
    
    header_row_m = None
    for row in reader_m:
        if len(row) > 5 and row[0].strip() == '':
            header_row_m = row
            break
            
    if not header_row_m:
        st.error("Could not find the header row in Matchups CSV. Make sure it's the vS Gold format.")
        st.stop()
        
    archetypes = [h.strip() for h in header_row_m[1:] if h.strip()]
    
    win_rates = {}
    for row in reader_m:
        if not row or row == header_row_m or not row[0].strip(): continue
        if len(row) > len(archetypes) // 2:
            my_d = str(row[0]).strip()
            win_rates[my_d] = {}
            for i, opp_deck in enumerate(archetypes):
                try:
                    val = float(row[i+1])
                    if val > 1.5: val = val / 100.0
                    win_rates[my_d][opp_deck] = val
                except:
                    win_rates[my_d][opp_deck] = 0.5

    mastery_logs = []
    if file_mastery:
        df_mastery = pd.read_csv(file_mastery)
        win_rates, mastery_logs = apply_mastery_adjustments(win_rates, df_mastery)

    class_map = defaultdict(list)
    for d in archetypes:
        class_map[get_class_from_deck(d)].append(d)
    all_classes = list(class_map.keys())

    content_deck = file_deck_freq.getvalue().decode('utf-8-sig')
    reader_d = list(csv.reader(io.StringIO(content_deck)))
    try:
        header_row_d = next(r for r in reader_d if r and r[0].strip() == 'Rank')
        l_index = header_row_d.index('L')
        deck_freqs = {}
        for row in reader_d:
            if not row or row == header_row_d: continue
            try: deck_freqs[row[0].strip()] = float(row[l_index])
            except: pass
    except StopIteration:
        st.sidebar.error("Could not find 'Rank' row in Deck Frequency.")
        st.stop()

    content_class = file_class_freq.getvalue().decode('utf-8-sig')
    reader_c = list(csv.reader(io.StringIO(content_class)))
    try:
        header_row_c = next(r for r in reader_c if r and r[0].strip() == 'Rank')
        l_index_c = header_row_c.index('L')
        class_freqs = {}
        for row in reader_c:
            if not row or row == header_row_c: continue
            try: class_freqs[row[0].strip()] = float(row[l_index_c])
            except: pass
    except StopIteration:
        st.sidebar.error("Could not find 'Rank' row in Class Frequency.")
        st.stop()

    arch_weights = {}
    for cls, decks in class_map.items():
        total_cls_freq = sum(deck_freqs.get(d, 0.0) for d in decks)
        for d in decks:
            if total_cls_freq > 0: 
                arch_weights[d] = deck_freqs.get(d, 0.0) / total_cls_freq
            else: 
                arch_weights[d] = 1.0 / len(decks)

    # --- MAIN APP UI ---
    tab1, tab2, tab3 = st.tabs(["1️⃣ Class Lineup Optimizer", "2️⃣ Archetype & Ban Optimizer", "3️⃣ Live Match Tracker"])

    # === TAB 1: PHASE 1 ===
    with tab1:
        st.header("Phase 1: Broad Class Lineup Optimizer")
        st.write("Generates the best 4-class lineups against the general ladder meta. Incorporates 'optionality value' by dynamically picking the best archetype per class based on the opponent's simulated lineup.")
        st.write("**Cohesion Score:** Shows how many of your decks directly benefit from banning the 'Target Ban' class (win rate < 50% vs that class). A score of 3/4 or 4/4 means strong Ban Synergy.")
        
        if mastery_logs:
            with st.expander("🛠️ Mastery Adjustments Applied", expanded=True):
                for log in mastery_logs:
                    st.write(log)
        
        if st.button("Generate Recommended Class Lineups", type="primary"):
            with st.spinner("Simulating Field and Running Monte Carlo Matchups..."):
                meta_field = []
                for _ in range(150):
                    opp_classes = get_weighted_classes(all_classes, class_freqs, 4)
                    opp_decks = []
                    for c in opp_classes:
                        best_d = max(class_map[c], key=lambda d: arch_weights.get(d, 1.0))
                        opp_decks.append(best_d)
                    meta_field.append(opp_decks)

                class_combos = list(itertools.combinations(all_classes, 4))
                all_results = []
                
                for my_class_combo in class_combos:
                    matchup_wrs = []
                    for opp_decks in meta_field:
                        my_dynamic_decks = []
                        for c in my_class_combo:
                            best_arch = max(class_map[c], key=lambda d: sum(win_rates.get(d, {}).get(od, 0.5) for od in opp_decks))
                            my_dynamic_decks.append(best_arch)
                            
                        wr = simulate_conquest_bo5(list(my_dynamic_decks), list(opp_decks), win_rates, iterations=100)
                        matchup_wrs.append(wr)
                        
                    # --- Calculate Cohesion & Target Ban ---
                    baseline_my_decks = [max(class_map[c], key=lambda d: arch_weights.get(d, 1.0)) for c in my_class_combo]
                    
                    lowest_avg_wr = 1.0
                    target_ban_class = None
                    cohesion_score = 0
                    
                    for opp_c in all_classes:
                        opp_baseline_deck = max(class_map[opp_c], key=lambda d: arch_weights.get(d, 1.0))
                        
                        wrs_against_target = [win_rates.get(my_d, {}).get(opp_baseline_deck, 0.5) for my_d in baseline_my_decks]
                        avg_wr = sum(wrs_against_target) / 4.0
                        
                        if avg_wr < lowest_avg_wr:
                            lowest_avg_wr = avg_wr
                            target_ban_class = opp_c
                            cohesion_score = sum(1 for w in wrs_against_target if w < 0.5)

                    all_results.append({
                        "Class Lineup": ", ".join(my_class_combo),
                        "Expected WR": statistics.mean(matchup_wrs),
                        "Floor": min(matchup_wrs),
                        "Target Ban": target_ban_class,
                        "Cohesion": f"{cohesion_score}/4 Protected"
                    })

                all_results = sorted(all_results, key=lambda x: x["Expected WR"], reverse=True)
                
                st.subheader("🔥 Top 10 Class Lineups")
                df_results = pd.DataFrame(all_results[:10])
                df_results.index = df_results.index + 1
                
                st.dataframe(df_results.style.format({
                    "Expected WR": "{:.2f}%", 
                    "Floor": "{:.2f}%"
                }), use_container_width=True)


    # === TAB 2: PHASE 2 ===
    with tab2:
        st.header("Phase 2: Archetype & Ban Optimizer")
        st.write("Calculates EXACT Nash Equilibrium BO5 win rates. We recommend the optimal archetypes by default, but you can override them to explore different ban matrices.")
        
        col1, col2 = st.columns(2)
        with col1:
            my_classes = st.multiselect("Select My 4 Classes", all_classes, max_selections=4)
        with col2:
            opp_classes = st.multiselect("Select Opponent's 4 Classes", all_classes, max_selections=4)

        if len(my_classes) == 4 and len(opp_classes) == 4:
            opp_4 = [max(class_map[c], key=lambda d: arch_weights.get(d, 1.0)) for c in opp_classes]

            cache_key = tuple(sorted(my_classes)) + tuple(sorted(opp_4))
            if st.session_state.get('phase2_cache_key') != cache_key:
                with st.spinner("Finding optimal archetypes..."):
                    my_options = [class_map[c] for c in my_classes]
                    all_my_combos = list(itertools.product(*my_options))
                    best_combo = None
                    best_wr = -1
                    nash_memo = {}
                    for combo in all_my_combos:
                        ban_matrix = get_ban_matrix(list(combo), opp_4, win_rates, nash_memo)
                        my_ban_p, opp_ban_p, match_wr = solve_zero_sum(ban_matrix)
                        if match_wr > best_wr:
                            best_wr = match_wr
                            best_combo = list(combo)
                    st.session_state['phase2_best_combo'] = best_combo
                    st.session_state['phase2_cache_key'] = cache_key

            best_combo = st.session_state['phase2_best_combo']

            st.write("---")
            st.subheader("🛠️ Custom Lineup Editor")
            st.write("The dropdowns below are pre-loaded with the **mathematically optimal archetypes**. Change them to see how the matrix shifts.")

            sel_cols = st.columns(4)
            selected_my_4 = []
            
            for i, c in enumerate(my_classes):
                options = class_map[c]
                default_deck = best_combo[i]
                default_idx = options.index(default_deck) if default_deck in options else 0
                
                with sel_cols[i]:
                    chosen_deck = st.selectbox(f"Your {c}", options, index=default_idx)
                    selected_my_4.append(chosen_deck)

            st.write("---")
            st.subheader("Expected Opponent Lineup")
            st.info(" , ".join(opp_4))

            nash_memo = {}
            ban_matrix = get_ban_matrix(selected_my_4, opp_4, win_rates, nash_memo)
            my_ban_p, opp_ban_p, match_wr = solve_zero_sum(ban_matrix)
            
            best_my_ban = opp_4[my_ban_p.index(max(my_ban_p))]
            best_opp_ban = selected_my_4[opp_ban_p.index(max(opp_ban_p))]

            st.success(f"### Expected Match Win Rate: {match_wr * 100:.2f}%")
            
            res_col1, res_col2 = st.columns(2)
            with res_col1:
                st.error(f"🛑 **YOU SHOULD BAN:** {best_my_ban}")
            with res_col2:
                st.warning(f"🛑 **EXPECT THEM TO BAN:** {best_opp_ban}")

            st.write("---")
            st.write("### 🧮 4x4 Ban Matrix (BO5 Expected Win Rates)")
            st.write("*Rows are the deck YOU ban. Columns are the deck THEY ban. The cell value is YOUR expected win rate.*")
            
            df_ban = pd.DataFrame(
                ban_matrix, 
                index=[f"Ban {d}" for d in opp_4], 
                columns=[f"Ban {d}" for d in selected_my_4]
            )
            
            st.dataframe(df_ban.style.format("{:.2%}").background_gradient(cmap='RdYlGn', axis=None), use_container_width=True)

    # === TAB 3: PHASE 3 ===
    with tab3:
        st.header("Phase 3: Live Match Tracker & Nash Queue")
        
        if 't_active' not in st.session_state:
            st.session_state.t_active = False
            st.session_state.t_my_rem = []
            st.session_state.t_opp_status = {}
            st.session_state.t_history = []
            if 't_nash_roll' in st.session_state:
                del st.session_state['t_nash_roll']

        if not st.session_state.t_active:
            st.write("Select your **3 specific active decks** and the opponent's **3 known classes** (post-ban) to begin.")
            c1, c2 = st.columns(2)
            with c1:
                start_my = st.multiselect("My 3 Active Decks", archetypes, max_selections=3)
            with c2:
                start_opp_classes = st.multiselect("Opponent's 3 Active Classes", all_classes, max_selections=3)
                
            if st.button("Start Live Match", type="primary"):
                if len(start_my) == 3 and len(start_opp_classes) == 3:
                    st.session_state.t_active = True
                    st.session_state.t_my_rem = list(start_my)
                    st.session_state.t_opp_status = {c: "Unknown" for c in start_opp_classes}
                    st.session_state.t_history = []
                    if 't_nash_roll' in st.session_state:
                        del st.session_state['t_nash_roll']
                    st.rerun()
                else:
                    st.error("Select exactly 3 decks for yourself and 3 classes for the opponent.")
                    
        else:
            if not st.session_state.t_my_rem:
                st.success("🎉 **MATCH OVER! YOU WON!**")
            elif not st.session_state.t_opp_status:
                st.error("💀 **MATCH OVER! OPPONENT WON!**")
            else:
                st.write("### 🔍 Opponent Lineup Status")
                st.write("Use the dropdowns to lock in the opponent's specific archetypes as they play them.")
                
                opp_cols = st.columns(len(st.session_state.t_opp_status))
                for i, (c, status) in enumerate(st.session_state.t_opp_status.items()):
                    with opp_cols[i]:
                        if status == "Unknown":
                            options = ["Unknown", f"Off-Meta {c}"] + class_map[c]
                            revealed = st.selectbox(f"{c} Archetype:", options, key=f"rev_{c}")
                            if revealed != "Unknown":
                                st.session_state.t_opp_status[c] = revealed
                                if 't_nash_roll' in st.session_state: del st.session_state['t_nash_roll']
                                st.rerun()
                        else:
                            st.success(f"**{c}**\n{status}")
                            if st.button("Undo", key=f"undo_{c}"):
                                st.session_state.t_opp_status[c] = "Unknown"
                                if 't_nash_roll' in st.session_state: del st.session_state['t_nash_roll']
                                st.rerun()
                            
                st.write("---")

                assumed_opp_rem = []
                for c, status in st.session_state.t_opp_status.items():
                    if status == "Unknown":
                        best_guess = max(class_map[c], key=lambda d: arch_weights.get(d, 1.0))
                        assumed_opp_rem.append(best_guess)
                    else:
                        assumed_opp_rem.append(status)
                        
                memo = {}
                val, my_p, opp_p = get_nash_queue(st.session_state.t_my_rem, assumed_opp_rem, win_rates, memo)
                
                st.write(f"### 🎯 Current BO5 Win Probability: {val * 100:.1f}%")
                
                recommendations = [(st.session_state.t_my_rem[i], my_p[i]) for i in range(len(my_p))]
                recommendations.sort(key=lambda x: x[1], reverse=True)
                
                st.info(f"💡 **NASH RECOMMENDATION: Queue {recommendations[0][0]}** ({recommendations[0][1]*100:.1f}% mix frequency)")
                
                if len(recommendations) > 1:
                    with st.expander("View full mixed strategy math"):
                        st.write("If you want to roll a die, use these exact probabilities:")
                        for deck, prob in recommendations:
                            if prob > 0.01:
                                st.write(f"- {deck}: {prob*100:.1f}%")

                if st.button("🎲 Roll the Die (Nash Pick)"):
                    decks = [r[0] for r in recommendations]
                    weights = [r[1] for r in recommendations]
                    if sum(weights) > 0:
                        st.session_state.t_nash_roll = random.choices(decks, weights=weights, k=1)[0]
                    else:
                        st.session_state.t_nash_roll = decks[0]
                        
                if st.session_state.get('t_nash_roll'):
                    st.success(f"🎲 **The Nash Die has spoken! You should queue:** {st.session_state.t_nash_roll}")

                st.write("---")
                
                st.write("### 📝 Record Game Result")
                rc1, rc2 = st.columns(2)
                with rc1:
                    played_my = st.selectbox("I played:", st.session_state.t_my_rem)
                    if st.button("🟢 I Won (Remove my deck)"):
                        st.session_state.t_my_rem.remove(played_my)
                        st.session_state.t_history.append(f"🟢 **WIN:** {played_my} won")
                        if 't_nash_roll' in st.session_state: del st.session_state['t_nash_roll']
                        st.rerun()
                with rc2:
                    opp_classes_rem = list(st.session_state.t_opp_status.keys())
                    played_opp_c = st.selectbox("Opponent played class:", opp_classes_rem)
                    
                    if st.session_state.t_opp_status[played_opp_c] == "Unknown":
                        st.warning("⚠️ Reveal their specific archetype above before logging their win.")
                    else:
                        if st.button("🔴 Opponent Won (Remove their deck)"):
                            played_arch = st.session_state.t_opp_status[played_opp_c]
                            del st.session_state.t_opp_status[played_opp_c]
                            st.session_state.t_history.append(f"🔴 **LOSS:** {played_my} lost to {played_arch}")
                            if 't_nash_roll' in st.session_state: del st.session_state['t_nash_roll']
                            st.rerun()
            
            if st.session_state.t_history:
                st.write("---")
                st.write("#### 📜 Match History")
                for i, log in enumerate(st.session_state.t_history):
                    st.write(f"**Game {i+1}:** {log}")
                    
                if not st.session_state.t_my_rem or not st.session_state.t_opp_status:
                    st.write("### 📋 Export Match Log")
                    
                    my_score = sum(1 for log in st.session_state.t_history if "🟢 **WIN:**" in log)
                    opp_score = sum(1 for log in st.session_state.t_history if "🔴 **LOSS:**" in log)
                    winner = "Player (You)" if my_score > opp_score else "Opponent"
                    
                    clean_logs = [
                        f"Winner: {winner}",
                        f"Final Score: {my_score} - {opp_score}",
                        "-------------------"
                    ]
                    
                    for i, log in enumerate(st.session_state.t_history):
                        clean_txt = log.replace("🟢 **WIN:** ", "WIN: ").replace("🔴 **LOSS:** ", "LOSS: ")
                        clean_logs.append(f"Game {i+1}: {clean_txt}")
                    
                    st.code("\n".join(clean_logs), language="text")

            st.write("---")
            btn_text = "End / Reset Match" if (not st.session_state.t_my_rem or not st.session_state.t_opp_status) else "Abort / Reset Match"
            if st.button(btn_text, type="secondary"):
                st.session_state.t_active = False
                st.rerun()

else:
    st.info("👈 Please upload the required CSV files in the sidebar to begin.")
