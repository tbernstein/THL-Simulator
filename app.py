import streamlit as st
import csv
import itertools
import random
from collections import defaultdict

# --- CONFIG ---
st.set_page_config(page_title="THL Strategy Command V5 (vS Integration)", layout="wide")

def get_class_from_deck(deck_name):
    return deck_name.split()[-1]

def get_weighted_classes(classes, class_weights, k=4):
    """Picks unique classes based on the uploaded weights."""
    chosen = set()
    while len(chosen) < k:
        weights = [class_weights.get(c, 1.0) for c in classes]
        if sum(weights) == 0: weights = [1.0] * len(classes) # Fallback
        pick = random.choices(classes, weights=weights, k=1)[0]
        chosen.add(pick)
    return list(chosen)

def get_archetype_prob(deck_name, arch_weights):
    """Returns archetype internal probability. Defaults to 1.0 if unknown."""
    return arch_weights.get(deck_name, 1.0)

def simulate_conquest_bo5(my_decks, opp_decks, win_rates, iterations=300):
    wins = 0
    for _ in range(iterations):
        my_rem, opp_rem = list(my_decks), list(opp_decks)
        while my_rem and opp_rem:
            my_p, opp_p = random.choice(my_rem), random.choice(opp_rem)
            wr = win_rates.get(my_p, {}).get(opp_p, 0.5)
            if random.random() < wr: my_rem.remove(my_p)
            else: opp_rem.remove(opp_p)
        if not my_rem: wins += 1
    return (wins / iterations) * 100

# --- vS DATA LOADERS ---
def load_vs_matchups(uploaded_file):
    win_rates, archetypes = {}, []
    content = uploaded_file.getvalue().decode('utf-8-sig').splitlines()
    reader = list(csv.reader(content))
    
    # 1. Hunt for the Header Row (First row starting with a blank/space and has many columns)
    header_row = None
    for row in reader:
        if len(row) > 5 and row[0].strip() == '':
            header_row = row
            break
            
    if not header_row: return {}, []
    
    archetypes = [h.strip() for h in header_row[1:] if h.strip()]
    
    # 2. Parse data using decimals directly
    for row in reader:
        if not row or not row[0].strip() or row == header_row: continue
        my_d = row[0].strip()
        win_rates[my_d] = {}
        for i, opp_deck in enumerate(archetypes):
            try:
                win_rates[my_d][opp_deck] = float(row[i+1]) # Raw vS decimal
            except:
                win_rates[my_d][opp_deck] = 0.5
    return win_rates, archetypes

def load_vs_frequencies(uploaded_file):
    freqs = {}
    content = uploaded_file.getvalue().decode('utf-8-sig').splitlines()
    reader = csv.reader(content)
    
    # 1. Hunt for the "Rank" Header Row
    header_row = None
    for row in reader:
        if row and row[0].strip() == 'Rank':
            header_row = [c.strip() for c in row]
            break
            
    if not header_row: return {}
    
    try:
        l_index = header_row.index('L') # Locate the Legend column
    except ValueError:
        return {}
        
    # 2. Parse the Legend frequencies
    for row in reader:
        if not row or not row[0].strip() or row == header_row: continue
        name = row[0].strip()
        try:
            freqs[name] = float(row[l_index])
        except:
            pass
    return freqs

# --- UI ---
st.title("🛡️ THL Strategist: Legacy Division")
st.write("Powered by automated Vicious Syndicate Data ingestion.")

st.sidebar.header("vS Raw Data Uploads")
matchup_file = st.sidebar.file_uploader("1. Matchup Table (.csv)", type=['csv'])
class_file = st.sidebar.file_uploader("2. Class Frequency (.csv)", type=['csv'])
deck_file = st.sidebar.file_uploader("3. Deck Frequency (.csv)", type=['csv'])

if matchup_file:
    win_rates, archetypes = load_vs_matchups(matchup_file)
    class_map = defaultdict(list)
    for d in archetypes: class_map[get_class_from_deck(d)].append(d)
    all_classes = list(class_map.keys())
    
    # Process vS Weights if provided
    class_weights = {}
    arch_weights = {}
    
    if class_file and deck_file:
        raw_class_freqs = load_vs_frequencies(class_file)
        raw_deck_freqs = load_vs_frequencies(deck_file)
        
        # Class weights are direct mappings from Legend column
        class_weights = raw_class_freqs
        
        # Calculate Internal Archetype Weights
        # (e.g. converting global 8% Egg Warlock to 80% Warlock representation)
        for cls, decks in class_map.items():
            total_cls_freq = sum(raw_deck_freqs.get(d, 0.0) for d in decks)
            for d in decks:
                if total_cls_freq > 0:
                    arch_weights[d] = raw_deck_freqs.get(d, 0.0) / total_cls_freq
                else:
                    arch_weights[d] = 1.0 / len(decks)
    else:
        st.sidebar.warning("Missing frequency data. Simulator will assume all classes and decks are equally likely.")

    phase = st.sidebar.selectbox("Workflow Step", [
        "Phase 1: Lineup Builder", 
        "Phase 2: Match Day (Ban EV)", 
        "Phase 4: Live Tracker"
    ])

    # --- PHASE 1: LINEUP BUILDER ---
    if phase == "Phase 1: Lineup Builder":
        st.header("Phase 1: Pre-Lock Lineup Optimization")
        st.write("Simulates against the field using your vS Legend class & deck distributions.")
        
        if st.button("Run Simulation (Takes ~10 sec)"):
            with st.spinner('Running Monte Carlo simulations against the meta...'):
                best_overall_wr = 0
                best_class_lineup = []
                class_combos = list(itertools.combinations(all_classes, 4))
                
                meta_field = []
                for _ in range(100):
                    opp_classes = get_weighted_classes(all_classes, class_weights, 4)
                    opp_decks = []
                    for c in opp_classes:
                        options = class_map[c]
                        # Opponent brings the most popular archetype for their class
                        best_d = max(options, key=lambda d: get_archetype_prob(d, arch_weights))
                        opp_decks.append(best_d)
                    meta_field.append(opp_decks)

                for my_class_combo in class_combos:
                    my_archetype_lists = [class_map[c] for c in my_class_combo]
                    total_wr = 0
                    for opp_decks in meta_field:
                        best_post_reveal_wr = 0
                        for my_deck_combo in itertools.product(*my_archetype_lists):
                            wr = simulate_conquest_bo5(random.sample(list(my_deck_combo), 3), random.sample(opp_decks, 3), win_rates, iterations=100)
                            if wr > best_post_reveal_wr: 
                                best_post_reveal_wr = wr
                        total_wr += best_post_reveal_wr
                    
                    avg_wr = total_wr / len(meta_field)
                    if avg_wr > best_overall_wr:
                        best_overall_wr = avg_wr
                        best_class_lineup = my_class_combo

                st.success(f"### Expected Series WR: {best_overall_wr:.2f}%")
                st.write("**Recommended Classes to Lock:**")
                for c in best_class_lineup:
                    st.write(f"- **{c}**")

    # --- PHASE 2: MATCH DAY ---
    elif phase == "Phase 2: Match Day (Ban EV)":
        st.header("Phase 2: Match Day Ban Optimizer (Weighted Expected Value)")
        col1, col2 = st.columns(2)
        with col1: my_lineup = st.multiselect("Your 4 Decks:", archetypes, max_selections=4)
        with col2: opp_classes = st.multiselect("Opponent's 4 Classes:", all_classes, max_selections=4)

        if len(my_lineup) == 4 and len(opp_classes) == 4:
            if st.button("Generate Strategy"):
                results = []
                for ban_c in opp_classes:
                    rem_classes = [c for c in opp_classes if c != ban_c]
                    opp_combos = list(itertools.product(*[class_map[c] for c in rem_classes]))
                    
                    worst_case_wr = 101
                    best_lead_for_this_ban = None
                    
                    for my_ban in my_lineup:
                        my_rem = [d for d in my_lineup if d != my_ban]
                        expected_wr = 0
                        total_prob = 0
                        
                        for opp_combo in opp_combos:
                            prob = 1.0
                            for d in opp_combo: prob *= get_archetype_prob(d, arch_weights)
                            total_prob += prob
                            
                            wr = simulate_conquest_bo5(my_rem, list(opp_combo), win_rates)
                            expected_wr += (wr * prob)
                            
                        expected_wr = expected_wr / total_prob if total_prob > 0 else expected_wr
                        
                        if expected_wr < worst_case_wr:
                            worst_case_wr = expected_wr
                            
                            leads = {}
                            for md in my_rem:
                                ev_lead = 0
                                lead_prob = 0
                                for od in list(itertools.chain(*[class_map[c] for c in rem_classes])):
                                    p = get_archetype_prob(od, arch_weights)
                                    ev_lead += win_rates.get(md, {}).get(od, 0.5) * p
                                    lead_prob += p
                                leads[md] = ev_lead / lead_prob if lead_prob > 0 else ev_lead
                            best_lead_for_this_ban = max(leads, key=leads.get)

                    results.append({"ban": ban_c, "wr": worst_case_wr, "lead": best_lead_for_this_ban})
                
                best_option = max(results, key=lambda x: x['wr'])
                st.success(f"### 🛑 Optimal Ban: {best_option['ban']}")
                st.metric("Expected Series Win Rate", f"{best_option['wr']:.1f}%")
                st.info(f"👉 **Game 1 Lead:** {best_option['lead']}")

    # --- PHASE 4: LIVE TRACKER ---
    elif phase == "Phase 4: Live Tracker":
        st.header("Phase 4: Fog of War Tracker")
        
        if 'match_active' not in st.session_state: st.session_state.match_active = False
        
        if not st.session_state.match_active:
            st.info("Input your 3 specific decks, and the opponent's 3 remaining CLASSES.")
            my_u = st.multiselect("Your 3 Unbanned Decks", archetypes, max_selections=3)
            opp_u = st.multiselect("Opponent's 3 Unbanned Classes", all_classes, max_selections=3)
            
            if st.button("Initialize Match"):
                st.session_state.my_rem = my_u
                st.session_state.opp_status = {c: "Unknown" for c in opp_u}
                st.session_state.match_active = True
                st.rerun()
        else:
            col1, col2 = st.columns(2)
            with col1: st.subheader(f"Your Decks Left: {len(st.session_state.my_rem)}")
            with col2: 
                st.subheader("Opponent Status:")
                for c, d in st.session_state.opp_status.items():
                    st.write(f"- {c}: **{d}**")
            
            if not st.session_state.my_rem:
                st.success("🎉 YOU WON! Report the score in Discord.")
                if st.button("Reset"): st.session_state.match_active = False; st.rerun()
            elif not st.session_state.opp_status:
                st.error("💀 You lost. Save your screenshots.")
                if st.button("Reset"): st.session_state.match_active = False; st.rerun()
            else:
                st.write("---")
                st.write("### 🔍 Reveal Opponent Archetype")
                reveal_c = st.selectbox("If they played an unknown deck, log it here:", [c for c, d in st.session_state.opp_status.items() if d == "Unknown"])
                if reveal_c:
                    reveal_d = st.selectbox(f"What {reveal_c} deck was it?", class_map[reveal_c])
                    if st.button("Lock Archetype"):
                        st.session_state.opp_status[reveal_c] = reveal_d
                        st.rerun()

                st.write("---")
                best_lead, best_floor = None, -1
                for my_deck in st.session_state.my_rem:
                    worst_mu = 101
                    for opp_c, opp_d in st.session_state.opp_status.items():
                        if opp_d != "Unknown":
                            mu = win_rates.get(my_deck, {}).get(opp_d, 0.5)
                        else:
                            ev = 0; p_total = 0
                            for possible_d in class_map[opp_c]:
                                p = get_archetype_prob(possible_d, arch_weights)
                                ev += win_rates.get(my_deck, {}).get(possible_d, 0.5) * p
                                p_total += p
                            mu = ev / p_total if p_total > 0 else ev
                        if mu < worst_mu: worst_mu = mu
                        
                    if worst_mu > best_floor:
                        best_floor = worst_mu
                        best_lead = my_deck
                        
                st.info(f"👉 **Recommended Next Pick:** {best_lead} (Weighted Floor: {best_floor*100:.1f}%)")

                st.write("### ⚔️ Resolve Game")
                r_col1, r_col2 = st.columns(2)
                with r_col1:
                    my_played = st.selectbox("Deck you played:", st.session_state.my_rem)
                    if st.button("I Won"):
                        st.session_state.my_rem.remove(my_played)
                        st.rerun()
                with r_col2:
                    revealed_opp_decks = {c: d for c, d in st.session_state.opp_status.items() if d != "Unknown"}
                    if revealed_opp_decks:
                        opp_played_c = st.selectbox("Class they won with:", list(revealed_opp_decks.keys()))
                        if st.button("They Won"):
                            del st.session_state.opp_status[opp_played_c]
                            st.rerun()
                    else:
                        st.warning("You must 'Reveal' their archetype above before you can log their win.")
