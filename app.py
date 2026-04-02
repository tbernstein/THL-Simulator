import streamlit as st
import csv
import itertools
import random
from collections import defaultdict
import io

# --- CONFIG & WEIGHTS ---
st.set_page_config(page_title="THL Conquest Simulator", layout="wide")

CLASS_WEIGHTS = {
    "Druid": 40, "Warrior": 20, "Warlock": 15, "Shaman": 10,
    "DH": 5, "Paladin": 5, "Mage": 2, "Rogue": 1, "Hunter": 1, "DK": 1
}

# --- CORE LOGIC ---
def get_class_from_deck(deck_name):
    return deck_name.split()[-1]

def get_weighted_classes(classes, k=4):
    chosen = set()
    while len(chosen) < k:
        weights = [CLASS_WEIGHTS.get(c, 1) for c in classes]
        pick = random.choices(classes, weights=weights, k=1)[0]
        chosen.add(pick)
    return list(chosen)

def simulate_conquest_bo5(my_decks, opp_decks, win_rates, iterations=500):
    wins = 0
    for _ in range(iterations):
        my_remaining = list(my_decks)
        opp_remaining = list(opp_decks)
        while my_remaining and opp_remaining:
            my_pick = random.choice(my_remaining)
            opp_pick = random.choice(opp_remaining)
            wr = win_rates.get(my_pick, {}).get(opp_pick, 0.5)
            if random.random() < wr:
                my_remaining.remove(my_pick)
            else:
                opp_remaining.remove(opp_pick)
        if not my_remaining:
            wins += 1
    return (wins / iterations) * 100

# --- DATA LOADING ---
def load_matrix(uploaded_file):
    win_rates = {}
    archetypes = []
    content = uploaded_file.getvalue().decode('utf-8-sig').splitlines()
    reader = csv.reader(content)
    headers = next(reader)[1:]
    archetypes = [h.strip() for h in headers if h.strip()]
    
    for row in reader:
        if not row or not row[0].strip(): continue
        my_deck = row[0].strip()
        win_rates[my_deck] = {}
        for i, opp_deck in enumerate(archetypes):
            try:
                win_rates[my_deck][opp_deck] = float(row[i+1]) / 100.0
            except:
                win_rates[my_deck][opp_deck] = 0.5
    return win_rates, archetypes

# --- UI & PHASES ---
st.title("🛡️ THL Conquest Simulator V3 (Legacy Div)")

st.sidebar.header("1. Upload Data")
uploaded_file = st.sidebar.file_uploader("Upload meta.csv", type=['csv'])

if uploaded_file is not None:
    win_rates, archetypes = load_matrix(uploaded_file)
    
    class_to_archetypes = defaultdict(list)
    for deck in archetypes:
        class_to_archetypes[get_class_from_deck(deck)].append(deck)
    all_classes = list(class_to_archetypes.keys())

    st.sidebar.header("2. Select Phase")
    phase = st.sidebar.radio("Navigation", ["Phase 1: Class Lock", "Phase 2: Match Day", "Phase 3: Cheat Sheet", "Phase 4: Live Match"])

    # --- PHASE 1 ---
    if phase == "Phase 1: Class Lock":
        st.header("Phase 1: Pre-Lock Optimization")
        st.write("Calculates the best 4 classes to lock by maximizing optionality against a weighted meta.")
        if st.button("Run Phase 1 Simulation (Takes ~10 seconds)"):
            with st.spinner('Simulating 100 meta scenarios...'):
                best_overall_wr = 0
                best_class_lineup = []
                class_combos = list(itertools.combinations(all_classes, 4))
                
                meta_field = []
                for _ in range(100):
                    opp_classes = get_weighted_classes(all_classes, 4)
                    opp_decks = [class_to_archetypes[c][0] for c in opp_classes]
                    meta_field.append(opp_decks)

                for my_class_combo in class_combos:
                    my_archetype_lists = [class_to_archetypes[c] for c in my_class_combo]
                    total_wr = 0
                    for opp_decks in meta_field:
                        best_post_reveal_wr = 0
                        for my_deck_combo in itertools.product(*my_archetype_lists):
                            wr = simulate_conquest_bo5(random.sample(list(my_deck_combo), 3), random.sample(opp_decks, 3), win_rates, iterations=100)
                            if wr > best_post_reveal_wr: best_post_reveal_wr = wr
                        total_wr += best_post_reveal_wr
                    
                    avg_wr = total_wr / len(meta_field)
                    if avg_wr > best_overall_wr:
                        best_overall_wr = avg_wr
                        best_class_lineup = my_class_combo

                st.success(f"### Expected Series WR: {best_overall_wr:.2f}%")
                st.write("**Recommended Classes to Lock:**")
                for c in best_class_lineup:
                    st.write(f"- **{c}** (Available options: {', '.join(class_to_archetypes[c])})")
                st.info("Lock these 4 classes on the THL website by Thursday, 11:59 PM Pacific.")

    # --- PHASE 2 ---
    elif phase == "Phase 2: Match Day":
        st.header("Phase 2: Ban & Game 1 Lead Optimizer")
        my_decks = st.multiselect("Select Your 4 Decks", archetypes, max_selections=4)
        opp_decks = st.multiselect("Select Opponent's 4 Decks", archetypes, max_selections=4)
        
        if len(my_decks) == 4 and len(opp_decks) == 4:
            if st.button("Calculate Match Strategy"):
                with st.spinner('Calculating worst-case scenarios...'):
                    best_ban = None
                    best_series_wr = -1
                    best_my_post_ban = []
                    best_opp_post_ban = []
                    
                    for ban_candidate in opp_decks:
                        opp_post_ban = [d for d in opp_decks if d != ban_candidate]
                        worst_case_wr = 101
                        expected_my_post_ban = []
                        for my_ban_candidate in my_decks:
                            my_post_ban = [d for d in my_decks if d != my_ban_candidate]
                            wr = simulate_conquest_bo5(my_post_ban, opp_post_ban, win_rates, iterations=1500)
                            if wr < worst_case_wr:
                                worst_case_wr = wr
                                expected_my_post_ban = my_post_ban
                        if worst_case_wr > best_series_wr:
                            best_series_wr = worst_case_wr
                            best_ban = ban_candidate
                            best_my_post_ban = expected_my_post_ban
                            best_opp_post_ban = opp_post_ban
                            
                    st.success(f"### 🛑 OPTIMAL BAN: {best_ban} (Worst-Case WR: {best_series_wr:.2f}%)")
                    
                    st.subheader("Game 1 Lead Recommendation")
                    best_lead, best_floor = None, -1
                    for my_deck in best_my_post_ban:
                        worst_mu = min(win_rates.get(my_deck, {}).get(opp_d, 0.5) for opp_d in best_opp_post_ban)
                        st.write(f"- {my_deck}: Worst-case matchup is {worst_mu*100:.1f}%")
                        if worst_mu > best_floor:
                            best_floor = worst_mu
                            best_lead = my_deck
                    st.info(f"**Play this deck Game 1:** {best_lead}")

    # --- PHASE 3 ---
    elif phase == "Phase 3: Cheat Sheet":
        st.header("Phase 3: Automated Ban Cheat Sheet")
        my_decks = st.multiselect("Select Your 4 Locked Decks", archetypes, max_selections=4)
        if len(my_decks) == 4:
            if st.button("Generate Cheat Sheet"):
                st.warning("This feature is best used locally due to Streamlit timeout limits on large combinatorics. For now, use Phase 2 for specific opponents!")

    # --- PHASE 4 ---
    elif phase == "Phase 4: Live Match":
        st.header("Phase 4: Live Match Tracker")
        
        if 'match_active' not in st.session_state: st.session_state.match_active = False
        
        if not st.session_state.match_active:
            my_start = st.multiselect("Your 3 Unbanned Decks", archetypes, max_selections=3)
            opp_start = st.multiselect("Opponent's 3 Unbanned Decks", archetypes, max_selections=3)
            if len(my_start) == 3 and len(opp_start) == 3:
                if st.button("Initialize Match"):
                    st.session_state.my_rem = my_start
                    st.session_state.opp_rem = opp_start
                    st.session_state.match_active = True
                    st.rerun()
        else:
            st.subheader(f"Your Decks Left: {', '.join(st.session_state.my_rem)}")
            st.subheader(f"Opponent Decks Left: {', '.join(st.session_state.opp_rem)}")
            
            if len(st.session_state.my_rem) == 0:
                st.success("🎉 YOU WON THE SERIES! Report the score in Discord.")
                if st.button("Reset Match"): st.session_state.match_active = False; st.rerun()
            elif len(st.session_state.opp_rem) == 0:
                st.error("💀 You lost the series. Save your screenshots.")
                if st.button("Reset Match"): st.session_state.match_active = False; st.rerun()
            else:
                st.write("---")
                if len(st.session_state.my_rem) == 1:
                    st.info(f"**Mandatory Pick:** You must play {st.session_state.my_rem[0]}")
                else:
                    best_lead, best_floor = None, -1
                    for my_deck in st.session_state.my_rem:
                        worst_mu = min(win_rates.get(my_deck, {}).get(opp_d, 0.5) for opp_d in st.session_state.opp_rem)
                        if worst_mu > best_floor:
                            best_floor = worst_mu
                            best_lead = my_deck
                    st.info(f"**Recommended Pick:** {best_lead} (Floor: {best_floor*100:.1f}%)")
                
                st.write("### Resolve Game")
                col1, col2 = st.columns(2)
                with col1:
                    my_played = st.selectbox("Deck you played:", st.session_state.my_rem)
                    if st.button("I Won Game"):
                        st.session_state.my_rem.remove(my_played)
                        st.rerun()
                with col2:
                    opp_played = st.selectbox("Deck they played:", st.session_state.opp_rem)
                    if st.button("They Won Game"):
                        st.session_state.opp_rem.remove(opp_played)
                        st.rerun()
else:
    st.info("Please upload your meta.csv file in the sidebar to begin.")
