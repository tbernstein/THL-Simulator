import streamlit as st
import csv
import itertools
import random
import statistics
import pandas as pd
import io
from collections import defaultdict

# --- CONFIG ---
st.set_page_config(page_title="THL Strategy Command V20", layout="wide")

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
    wins = 0
    rng = random.Random()
    rng.seed("".join(my_decks) + "".join(opp_decks))
    
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
    """
    Applies personal skill and deck complexity modifiers to the win rate matrix.
    Skill: 1 (+4%), 2 (0%), 3 (-6%)
    Complexity: 1 (1.5x), 2 (1.0x), 3 (0.5x)
    """
    if df_mastery is None or df_mastery.empty:
        return win_rates, []

    skill_bases = {1: 0.04, 2: 0.0, 3: -0.06}
    comp_mults = {1: 1.5, 2: 1.0, 3: 0.5}
    adjustment_logs = []

    for index, row in df_mastery.iterrows():
        deck_name = str(row.iloc[0]).strip()
        try:
            skill = int(row.iloc[1])
            complexity = int(row.iloc[2])
        except (ValueError, TypeError):
            continue # Skip invalid rows

        if skill in skill_bases and complexity in comp_mults:
            modifier = skill_bases[skill] * comp_mults[complexity]
            
            if deck_name in win_rates:
                for opp_deck in win_rates[deck_name]:
                    new_wr = win_rates[deck_name][opp_deck] + modifier
                    # Clamp between 5% and 95%
                    win_rates[deck_name][opp_deck] = max(0.05, min(0.95, new_wr))
                
                if modifier != 0:
                    adjustment_logs.append(f"**{deck_name}**: Adjusted overall expected WR by {modifier*100:+.1f}%")
                    
    return win_rates, adjustment_logs


# --- SIDEBAR UI: FILE UPLOADS ---
st.sidebar.header("📁 Step 1: Upload Data")

st.sidebar.markdown("""
**1. Matchup Table** *The raw win-rate matrix. Optimized for download from vS Gold. Rows are your decks, columns are opponents.*
""")
file_matchups = st.sidebar.file_uploader("Upload Matchup Table", type=['csv'], key="m_up")

st.sidebar.markdown("""
**2. Deck Frequency** *Contains the popularity of specific deck archetypes. Optimized for download from vS Gold.*
""")
file_deck_freq = st.sidebar.file_uploader("Upload Deck Frequency", type=['csv'], key="d_freq")

st.sidebar.markdown("""
**3. Class Frequency** *Contains the overall popularity of each class. Optimized for download from vS Gold.*
""")
file_class_freq = st.sidebar.file_uploader("Upload Class Frequency", type=['csv'], key="c_freq")

st.sidebar.markdown("""
**4. Mastery Data (New!)** *Adjusts win rates based on your proficiency. Format: 3 columns (`Deck Name`, `Skill` 1-3 [1=Best], `Complexity` 1-3 [1=Hardest]).*
""")
file_mastery = st.sidebar.file_uploader("Upload Mastery CSV (Optional)", type=['csv'], key="mastery")


# --- DATA PROCESSING ---
if file_matchups and file_deck_freq and file_class_freq:
    
    # 1. Load Matchups (Safely skipping vS metadata rows)
    content_matchups = file_matchups.getvalue().decode('utf-8-sig')
    reader_m = list(csv.reader(io.StringIO(content_matchups)))
    
    header_row_m = None
    for row in reader_m:
        # Find the row where the first cell is blank and it has many columns (the vS header)
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
        # Only process rows that look like matchup data
        if len(row) > len(archetypes) // 2:
            my_d = str(row[0]).strip()
            win_rates[my_d] = {}
            for i, opp_deck in enumerate(archetypes):
                try:
                    val = float(row[i+1])
                    if val > 1.5: val = val / 100.0  # Handle 54.0 vs 0.54
                    win_rates[my_d][opp_deck] = val
                except:
                    win_rates[my_d][opp_deck] = 0.5

    # 2. Apply Mastery
    mastery_logs = []
    if file_mastery:
        # Mastery CSV is user-generated, so pandas is safe here
        df_mastery = pd.read_csv(file_mastery)
        win_rates, mastery_logs = apply_mastery_adjustments(win_rates, df_mastery)

    # Class Mapping
    class_map = defaultdict(list)
    for d in archetypes:
        class_map[get_class_from_deck(d)].append(d)
    all_classes = list(class_map.keys())

    # 3. Load Deck Frequencies
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

    # 4. Load Class Frequencies
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

    # Calculate Weights
    arch_weights = {}
    for cls, decks in class_map.items():
        total_cls_freq = sum(deck_freqs.get(d, 0.0) for d in decks)
        for d in decks:
            if total_cls_freq > 0: 
                arch_weights[d] = deck_freqs.get(d, 0.0) / total_cls_freq
            else: 
                arch_weights[d] = 1.0 / len(decks)

    # --- MAIN APP UI ---
    tab1, tab2 = st.tabs(["🏆 Lineup Optimizer", "⚔️ Active Match Tracker"])

    # === TAB 1: OPTIMIZER ===
    with tab1:
        st.header("Conquest Lineup Optimizer")
        
        if mastery_logs:
            with st.expander("🛠️ Mastery Adjustments Applied", expanded=True):
                for log in mastery_logs:
                    st.write(log)
        
        if st.button("Generate Recommended Lineups", type="primary"):
            with st.spinner("Simulating Field and Running Monte Carlo Matchups..."):
                # Generate Meta Field
                meta_field = []
                for _ in range(150):
                    opp_classes = get_weighted_classes(all_classes, class_freqs, 4)
                    opp_decks = []
                    for c in opp_classes:
                        options = class_map[c]
                        best_d = max(options, key=lambda d: arch_weights.get(d, 1.0))
                        opp_decks.append(best_d)
                    meta_field.append(opp_decks)

                # Run Combos
                class_combos = list(itertools.combinations(all_classes, 4))
                all_results = []
                
                for my_class_combo in class_combos:
                    my_best_decks = [max(class_map[c], key=lambda d: arch_weights.get(d, 1.0)) for c in my_class_combo]
                    
                    matchup_wrs = []
                    for opp_decks in meta_field:
                        wr = simulate_conquest_bo5(list(my_best_decks), list(opp_decks), win_rates, iterations=100)
                        matchup_wrs.append(wr)
                        
                    all_results.append({
                        "Lineup": ", ".join(my_best_decks),
                        "Expected WR": statistics.mean(matchup_wrs),
                        "Floor": min(matchup_wrs),
                        "Favored %": sum(1 for w in matchup_wrs if w > 50.0) / len(matchup_wrs) * 100
                    })

                all_results = sorted(all_results, key=lambda x: x["Expected WR"], reverse=True)
                
                st.subheader("🔥 Top 10 Lineups")
                df_results = pd.DataFrame(all_results[:10])
                df_results.index = df_results.index + 1
                st.dataframe(df_results.style.format({
                    "Expected WR": "{:.2f}%", 
                    "Floor": "{:.2f}%", 
                    "Favored %": "{:.1f}%"
                }), use_container_width=True)

    # === TAB 2: MATCH TRACKER ===
    with tab2:
        st.header("Live Conquest Tracker")
        
        # Init State
        if 'history' not in st.session_state:
            st.session_state.history = []
            st.session_state.match_active = False
            st.session_state.my_rem = []
            st.session_state.opp_status = {}

        if not st.session_state.match_active:
            st.write("Start a new match to track bans and game history.")
            # Simplified manual start for the UI structure
            if st.button("Start New Match Tracker"):
                st.session_state.history = []
                st.session_state.match_active = True
                # Defaults just for testing UI functionality
                st.session_state.my_rem = list(archetypes[:3]) if archetypes else []
                st.session_state.opp_status = {c: "Unknown" for c in all_classes[:3]} if all_classes else {}
                st.rerun()
                
        if st.session_state.get('match_active'):
            st.write("### Current Match Record")
            
            my_played = st.selectbox("I am playing:", list(st.session_state.my_rem))
            opp_played_c = st.selectbox("Opponent class played:", list(st.session_state.opp_status.keys()))
            
            opp_d = st.session_state.opp_status.get(opp_played_c, "Unknown")
            opp_name = opp_d if opp_d != "Unknown" else f"Unknown {opp_played_c}"
            
            btn_col1, btn_col2 = st.columns(2)
            with btn_col1:
                if st.button("I Won"):
                    st.session_state.history.append(f"🟢 **WIN:** {my_played} vs {opp_name}")
                    if my_played in st.session_state.my_rem:
                        st.session_state.my_rem.remove(my_played)
                    st.rerun()
            with btn_col2:
                if opp_d == "Unknown":
                    st.warning("⚠️ Reveal their exact archetype above before you log their win.")
                else:
                    if st.button("They Won"):
                        st.session_state.history.append(f"🔴 **LOSS:** {my_played} vs {opp_name}")
                        if opp_played_c in st.session_state.opp_status:
                            del st.session_state.opp_status[opp_played_c]
                        st.rerun()
                        
            if st.session_state.get('history'):
                st.write("---")
                if not st.session_state.my_rem or not st.session_state.opp_status:
                    st.write("### 📜 Final Match Summary")
                    if st.button("End Match / Reset"):
                        st.session_state.match_active = False
                        st.rerun()
                else:
                    st.write("### 📜 Match History")
                    
                for i, game_log in enumerate(st.session_state.history):
                    st.write(f"**Game {i+1}:** {game_log}")

else:
    st.info("👈 Please upload the required CSV files in the sidebar to begin.")
