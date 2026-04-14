import streamlit as st
import csv
import itertools
import random
import statistics
import pandas as pd
import io
from collections import defaultdict

# --- CONFIG ---
st.set_page_config(page_title="THL Strategy Command V28", layout="wide")

# --- FORMAT SELECTION ---
st.sidebar.header("⚙️ Tournament Format")
match_format = st.sidebar.radio(
    "Select Ruleset:", 
    ["Legacy (Conquest)", "Hero (Last Hero Standing)"]
)
st.sidebar.write("---")

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

def get_nash_queue_conquest(my_rem, opp_rem, win_rates, memo):
    """Recursively calculates exact Conquest BO5 win rate."""
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
            # Conquest: I win -> my deck removed. I lose -> opp deck removed.
            v_win, _, _ = get_nash_queue_conquest([d for d in my_rem if d != m_deck], opp_rem, win_rates, memo)
            v_lose, _, _ = get_nash_queue_conquest(my_rem, [d for d in opp_rem if d != o_deck], win_rates, memo)
            row.append(wr * v_win + (1 - wr) * v_lose)
        matrix.append(row)

    my_p, opp_p, val = solve_zero_sum(matrix, iterations=2500)
    memo[state] = (val, my_p, opp_p)
    return val, my_p, opp_p

def get_lhs_val(my_rem, opp_rem, my_active, opp_active, win_rates, memo):
    """Recursively calculates exact Last Hero Standing BO5 win rate."""
    state = (tuple(sorted(my_rem)), tuple(sorted(opp_rem)), my_active, opp_active)
    if state in memo: return memo[state]
    
    if not my_rem: return 0.0, [], []
    if not opp_rem: return 1.0, [], []
    
    # Game 1: Simultaneous pick
    if my_active is None and opp_active is None:
        matrix = []
        for m in my_rem:
            row = []
            for o in opp_rem:
                val, _, _ = get_lhs_val(my_rem, opp_rem, m, o, win_rates, memo)
                row.append(val)
            matrix.append(row)
        # Reduced iterations for Hero mode performance protection
        my_p, opp_p, val = solve_zero_sum(matrix, iterations=1000)
        memo[state] = (val, my_p, opp_p)
        return val, my_p, opp_p

    # Active Match (Games 2-5)
    if my_active is not None and opp_active is not None:
        wr = win_rates.get(my_active, {}).get(opp_active, 0.5)
        
        # I win: Opponent's active deck is removed. They pick next to minimize my value.
        opp_rem_after_win = [d for d in opp_rem if d != opp_active]
        if not opp_rem_after_win:
            v_win = 1.0
        else:
            v_win = min([get_lhs_val(my_rem, opp_rem_after_win, my_active, next_o, win_rates, memo)[0] for next_o in opp_rem_after_win])
        
        # I lose: My active deck is removed. I pick next to maximize my value.
        my_rem_after_lose = [d for d in my_rem if d != my_active]
        if not my_rem_after_lose:
            v_lose = 0.0
        else:
            v_lose = max([get_lhs_val(my_rem_after_lose, opp_rem, next_m, opp_active, win_rates, memo)[0] for next_m in my_rem_after_lose])
            
        val = wr * v_win + (1 - wr) * v_lose
        memo[state] = (val, [], [])
        return val, [], []
        
    return 0.0, [], []

def get_ban_matrix(my_4, opp_4, win_rates, memo, mode):
    """Generates the 4x4 Ban Matrix to find optimal bans."""
    ban_matrix = []
    for my_ban in opp_4:
        row = []
        opp_3 = [d for d in opp_4 if d != my_ban]
        for opp_ban in my_4:
            my_3 = [d for d in my_4 if d != opp_ban]
            if mode == "Legacy (Conquest)":
                val, _, _ = get_nash_queue_conquest(my_3, opp_3, win_rates, memo)
            else:
                val, _, _ = get_lhs_val(my_3, opp_3, None, None, win_rates, memo)
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

def simulate_lhs_bo5(my_decks, opp_decks, win_rates, iterations=150):
    wins = 0
    rng = random.Random()
    for _ in range(iterations):
        my_rem, opp_rem = list(my_decks), list(opp_decks)
        my_active = rng.choice(my_rem)
        opp_active = rng.choice(opp_rem)
        
        while my_rem and opp_rem:
            wr = win_rates.get(my_active, {}).get(opp_active, 0.5)
            if rng.random() < wr:
                # I win
                opp_rem.remove(opp_active)
                if opp_rem:
                    opp_active = min(opp_rem, key=lambda d: win_rates.get(my_active, {}).get(d, 0.5))
            else:
                # Opp wins
                my_rem.remove(my_active)
                if my_rem:
                    my_active = max(my_rem, key=lambda d: win_rates.get(d, {}).get(opp_active, 0.5))
        if not opp_rem:
            wins += 1
    return (wins / iterations) * 100

def apply_mastery_adjustments(win_rates, df_mastery):
    if df_mastery is None or df_mastery.empty:
        return win_rates, []

    tier_modifiers = {
        'S': 0.045,  'A': 0.015,  'B': -0.035, 'C': -0.10   
    }
    
    adjustment_logs = []
    for index, row in df_mastery.iterrows():
        try:
            deck_name = str(row.iloc[0]).strip()
            tier = str(row.iloc[1]).strip().upper()
        except: continue

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
file_matchups = st.sidebar.file_uploader("1. Upload Matchup Table (vS Gold)", type=['csv'], key="m_up")
file_deck_freq = st.sidebar.file_uploader("2. Upload Deck Frequency", type=['csv'], key="d_freq")
file_class_freq = st.sidebar.file_uploader("3. Upload Class Frequency", type=['csv'], key="c_freq")
file_mastery = st.sidebar.file_uploader("4. Upload Mastery CSV (Optional)", type=['csv'], key="mastery")

# --- DATA PROCESSING ---
if file_matchups and file_deck_freq and file_class_freq:
    
    content_matchups = file_matchups.getvalue().decode('utf-8-sig')
    reader_m = list(csv.reader(io.StringIO(content_matchups)))
    
    header_row_m = None
    for row in reader_m:
        if len(row) > 5 and row[0].strip() == '':
            header_row_m = row; break
            
    if not header_row_m:
        st.error("Could not find the header row in Matchups CSV.")
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
    except: st.stop()

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
    except: st.stop()

    arch_weights = {}
    for cls, decks in class_map.items():
        total_cls_freq = sum(deck_freqs.get(d, 0.0) for d in decks)
        for d in decks:
            if total_cls_freq > 0: arch_weights[d] = deck_freqs.get(d, 0.0) / total_cls_freq
            else: arch_weights[d] = 1.0 / len(decks)

    # --- MAIN APP UI ---
    tab1, tab2, tab3 = st.tabs(["1️⃣ Class Lineup Optimizer", "2️⃣ Archetype & Ban Optimizer", "3️⃣ Live Match Tracker"])

    # === TAB 1: PHASE 1 ===
    with tab1:
        st.header(f"Phase 1: Broad Class Lineup Optimizer ({match_format})")
        st.write("Generates the best 4-class lineups against the general ladder meta. Incorporates 'optionality value'.")
        
        if mastery_logs:
            with st.expander("🛠️ Mastery Adjustments Applied", expanded=True):
                for log in mastery_logs: st.write(log)
        
        if st.button("Generate Recommended Class Lineups", type="primary"):
            with st.spinner("Simulating Field and Running Monte Carlo Matchups..."):
                meta_field = []
                for _ in range(150):
                    opp_classes = get_weighted_classes(all_classes, class_freqs, 4)
                    opp_decks = [max(class_map[c], key=lambda d: arch_weights.get(d, 1.0)) for c in opp_classes]
                    meta_field.append(opp_decks)

                class_combos = list(itertools.combinations(all_classes, 4))
                all_results = []
                
                for my_class_combo in class_combos:
                    matchup_wrs = []
                    for opp_decks in meta_field:
                        if match_format == "Legacy (Conquest)":
                            # Legacy: Optimize for highest average performance across the board
                            my_dynamic_decks = [max(class_map[c], key=lambda d: sum(win_rates.get(d, {}).get(od, 0.5) for od in opp_decks)) for c in my_class_combo]
                            wr = simulate_conquest_bo5(list(my_dynamic_decks), list(opp_decks), win_rates, iterations=100)
                        else:
                            # Hero Mode: Optimize for peak polarization (find the Slayer)
                            my_dynamic_decks = [max(class_map[c], key=lambda d: max([win_rates.get(d, {}).get(od, 0.5) for od in opp_decks])) for c in my_class_combo]
                            wr = simulate_lhs_bo5(list(my_dynamic_decks), list(opp_decks), win_rates, iterations=100)
                        matchup_wrs.append(wr)
                        
                    # Target Ban Logic changes based on format
                    baseline_my_decks = [max(class_map[c], key=lambda d: arch_weights.get(d, 1.0)) for c in my_class_combo]
                    
                    if match_format == "Legacy (Conquest)":
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
                    else: 
                        # Hero Mode Target Ban (Protect the Anchor)
                        anchor_deck = max(baseline_my_decks, key=lambda d: sum(win_rates.get(d, {}).get(max(class_map[oc], key=lambda x: arch_weights.get(x, 1.0)), 0.5) for oc in all_classes) / len(all_classes))
                        highest_opp_wr = -1
                        target_ban_class = None
                        for opp_c in all_classes:
                            opp_baseline_deck = max(class_map[opp_c], key=lambda d: arch_weights.get(d, 1.0))
                            opp_wr_against_anchor = 1.0 - win_rates.get(anchor_deck, {}).get(opp_baseline_deck, 0.5)
                            if opp_wr_against_anchor > highest_opp_wr:
                                highest_opp_wr = opp_wr_against_anchor
                                target_ban_class = opp_c
                        opp_counter_deck = max(class_map[target_ban_class], key=lambda d: arch_weights.get(d, 1.0))
                        
                        # FLIPPED: Now correctly calculates how many decks lose to the target ban, thus are "Protected"
                        cohesion_score = sum(1 for my_d in baseline_my_decks if win_rates.get(my_d, {}).get(opp_counter_deck, 0.5) < 0.5)

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
                st.dataframe(df_results.style.format({"Expected WR": "{:.2f}%", "Floor": "{:.2f}%"}), use_container_width=True)

    # === TAB 2: PHASE 2 ===
    with tab2:
        st.header(f"Phase 2: Archetype & Ban Optimizer ({match_format})")
        st.write("Calculates EXACT mathematical BO5 win rates.")
        
        col1, col2 = st.columns(2)
        with col1: my_classes = st.multiselect("Select My 4 Classes", all_classes, max_selections=4)
        with col2: opp_classes = st.multiselect("Select Opponent's 4 Classes", all_classes, max_selections=4)

        if len(my_classes) == 4 and len(opp_classes) == 4:
            opp_4 = [max(class_map[c], key=lambda d: arch_weights.get(d, 1.0)) for c in opp_classes]
            cache_key = tuple(sorted(my_classes)) + tuple(sorted(opp_4)) + (match_format,)
            
            if st.session_state.get('phase2_cache_key') != cache_key:
                if match_format == "Hero (Last Hero Standing)":
                    st.info("Hero Mode calculations take significantly longer. Please wait...")
                
                with st.spinner("Finding optimal archetypes..."):
                    my_options = [class_map[c] for c in my_classes]
                    all_my_combos = list(itertools.product(*my_options))
                    best_combo = None
                    best_wr = -1
                    nash_memo = {}
                    for combo in all_my_combos:
                        ban_matrix = get_ban_matrix(list(combo), opp_4, win_rates, nash_memo, match_format)
                        my_ban_p, opp_ban_p, match_wr = solve_zero_sum(ban_matrix)
                        if match_wr > best_wr:
                            best_wr = match_wr
                            best_combo = list(combo)
                    st.session_state['phase2_best_combo'] = best_combo
                    st.session_state['phase2_cache_key'] = cache_key

            best_combo = st.session_state['phase2_best_combo']

            st.write("---")
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
            st.info(f"**Expected Opponent Lineup:** {', '.join(opp_4)}")

            nash_memo = {}
            ban_matrix = get_ban_matrix(selected_my_4, opp_4, win_rates, nash_memo, match_format)
            my_ban_p, opp_ban_p, match_wr = solve_zero_sum(ban_matrix)
            
            best_my_ban = opp_4[my_ban_p.index(max(my_ban_p))]
            best_opp_ban = selected_my_4[opp_ban_p.index(max(opp_ban_p))]

            st.success(f"### Expected Match Win Rate: {match_wr * 100:.2f}%")
            
            res_col1, res_col2 = st.columns(2)
            with res_col1: st.error(f"🛑 **YOU SHOULD BAN:** {best_my_ban}")
            with res_col2: st.warning(f"🛑 **EXPECT THEM TO BAN:** {best_opp_ban}")

            st.write("---")
            st.write("### 🧮 4x4 Ban Matrix")
            df_ban = pd.DataFrame(ban_matrix, index=[f"Ban {d}" for d in opp_4], columns=[f"Ban {d}" for d in selected_my_4])
            st.dataframe(df_ban.style.format("{:.2%}").background_gradient(cmap='RdYlGn', axis=None), use_container_width=True)

    # === TAB 3: PHASE 3 ===
    with tab3:
        st.header(f"Phase 3: Live Match Tracker ({match_format})")
        
        if 't_active' not in st.session_state:
            st.session_state.t_active = False
            st.session_state.t_my_rem = []
            st.session_state.t_opp_status = {}
            st.session_state.t_history = []
            st.session_state.t_start_my = []
            st.session_state.t_start_opp_revealed = {}
            st.session_state.t_my_active = None
            st.session_state.t_opp_active = None

        if not st.session_state.t_active:
            st.write("Select your 3 specific active decks and the opponent's 3 classes to begin.")
            c1, c2 = st.columns(2)
            with c1: start_my = st.multiselect("My 3 Active Decks", archetypes, max_selections=3)
            with c2: start_opp_classes = st.multiselect("Opponent's 3 Active Classes", all_classes, max_selections=3)
                
            if st.button("Start Live Match", type="primary"):
                if len(start_my) == 3 and len(start_opp_classes) == 3:
                    st.session_state.t_active = True
                    st.session_state.t_my_rem = list(start_my)
                    st.session_state.t_opp_status = {c: "Unknown" for c in start_opp_classes}
                    st.session_state.t_start_my = list(start_my)
                    st.session_state.t_start_opp_revealed = {c: f"Unknown {c}" for c in start_opp_classes}
                    st.session_state.t_history = []
                    st.session_state.t_my_active = None
                    st.session_state.t_opp_active = None
                    if 't_nash_roll' in st.session_state: del st.session_state['t_nash_roll']
                    st.rerun()
                else: st.error("Select exactly 3 decks and 3 classes.")
                    
        else:
            if not st.session_state.t_my_rem:
                st.success("🎉 **MATCH OVER! YOU WON!**")
            elif not st.session_state.t_opp_status:
                st.error("💀 **MATCH OVER! OPPONENT WON!**")
            else:
                st.write("### 🔍 Opponent Lineup Status")
                opp_cols = st.columns(len(st.session_state.t_opp_status))
                for i, (c, status) in enumerate(st.session_state.t_opp_status.items()):
                    with opp_cols[i]:
                        if status == "Unknown":
                            options = ["Unknown", f"Off-Meta {c}"] + class_map[c]
                            revealed = st.selectbox(f"{c} Archetype:", options, key=f"rev_{c}")
                            if revealed != "Unknown":
                                st.session_state.t_opp_status[c] = revealed
                                st.session_state.t_start_opp_revealed[c] = revealed
                                if 't_nash_roll' in st.session_state: del st.session_state['t_nash_roll']
                                st.rerun()
                        else:
                            st.success(f"**{c}**\n{status}")
                            if st.button("Undo", key=f"undo_{c}"):
                                st.session_state.t_opp_status[c] = "Unknown"
                                st.session_state.t_start_opp_revealed[c] = f"Unknown {c}"
                                if 't_nash_roll' in st.session_state: del st.session_state['t_nash_roll']
                                st.rerun()
                st.write("---")

                assumed_opp_rem = []
                for c, status in st.session_state.t_opp_status.items():
                    if status == "Unknown":
                        best_guess = max(class_map[c], key=lambda d: arch_weights.get(d, 1.0))
                        assumed_opp_rem.append(best_guess)
                    else: assumed_opp_rem.append(status)
                        
                memo = {}
                recommendations = []
                
                if match_format == "Legacy (Conquest)":
                    val, my_p, opp_p = get_nash_queue_conquest(st.session_state.t_my_rem, assumed_opp_rem, win_rates, memo)
                    st.write(f"### 🎯 Current BO5 Win Probability: {val * 100:.1f}%")
                    recommendations = [(st.session_state.t_my_rem[i], my_p[i]) for i in range(len(my_p))]
                    recommendations.sort(key=lambda x: x[1], reverse=True)
                    st.info(f"💡 **NASH RECOMMENDATION: Queue {recommendations[0][0]}** ({recommendations[0][1]*100:.1f}% mix)")
                
                else: # Hero Mode Decision Guidance
                    if st.session_state.t_my_active is None and st.session_state.t_opp_active is None:
                        val, my_p, opp_p = get_lhs_val(st.session_state.t_my_rem, assumed_opp_rem, None, None, win_rates, memo)
                        st.write(f"### 🎯 Game 1 Lead Predictor (BO5 Win Probability: {val * 100:.1f}%)")
                        recommendations = [(st.session_state.t_my_rem[i], my_p[i]) for i in range(len(my_p))]
                        recommendations.sort(key=lambda x: x[1], reverse=True)
                        st.info(f"💡 **NASH LEAD RECOMMENDATION: Queue {recommendations[0][0]}** ({recommendations[0][1]*100:.1f}% mix)")
                        
                        # Added Sweep Potential explicitly for Game 1 Leads!
                        st.write("#### 🧹 Game 1 Sweep Potential:")
                        lead_sweeps = []
                        for m in st.session_state.t_my_rem:
                            sweep_prob = 1.0
                            for opp_rem_deck in assumed_opp_rem:
                                sweep_prob *= win_rates.get(m, {}).get(opp_rem_deck, 0.5)
                            lead_sweeps.append((m, sweep_prob))
                        
                        lead_sweeps.sort(key=lambda x: x[1], reverse=True)
                        for m, sweep in lead_sweeps:
                            st.write(f"- **{m}**: **{sweep*100:.1f}%** chance to 3-0 sweep")
                    
                    elif st.session_state.t_my_active is not None:
                        st.success(f"🔥 **You are King of the Hill!** Locked on **{st.session_state.t_my_active}**.")
                        opp_likely = min(assumed_opp_rem, key=lambda d: win_rates.get(st.session_state.t_my_active, {}).get(d, 0.5))
                        st.warning(f"Expect opponent to counter with: **{opp_likely}**")
                        
                    elif st.session_state.t_opp_active is not None:
                        st.error(f"💀 **Opponent is King of the Hill!** Locked on **{st.session_state.t_opp_active}**.")
                        st.write("### 🎯 Counter-Pick Recommendations")
                        counter_recs = []
                        for m in st.session_state.t_my_rem:
                            wr_vs_king = win_rates.get(m, {}).get(st.session_state.t_opp_active, 0.5)
                            # Sweep Potential: Chance to beat King * chance to beat remaining decks
                            sweep_prob = wr_vs_king
                            for opp_rem_deck in assumed_opp_rem:
                                if opp_rem_deck != st.session_state.t_opp_active:
                                    sweep_prob *= win_rates.get(m, {}).get(opp_rem_deck, 0.5)
                                    
                            counter_recs.append((m, wr_vs_king, sweep_prob))
                        
                        counter_recs.sort(key=lambda x: x[1], reverse=True)
                        for m, wr, sweep in counter_recs:
                            st.write(f"- **{m}**: Expected WR **{wr*100:.1f}%** vs King (🧹 Sweep Potential: **{sweep*100:.1f}%**)")

                # Conditionally show the Die Roll UI only when appropriate
                if match_format == "Legacy (Conquest)" or (match_format == "Hero (Last Hero Standing)" and st.session_state.t_my_active is None and st.session_state.t_opp_active is None):
                    if st.button("🎲 Roll the Die (Nash Pick)"):
                        if recommendations:
                            decks = [r[0] for r in recommendations]
                            weights = [r[1] for r in recommendations]
                            chosen = random.choices(decks, weights=weights, k=1)[0]
                            st.session_state.t_nash_roll = chosen
                            
                    if 't_nash_roll' in st.session_state:
                        st.success(f"🎲 The Die says: Queue **{st.session_state.t_nash_roll}**")

                st.write("---")
                st.write("### 📝 Record Game Result")
                
                rec_col1, rec_col2 = st.columns(2)
                with rec_col1:
                    if match_format == "Hero (Last Hero Standing)" and st.session_state.t_my_active:
                        played_my = st.selectbox("I played:", [st.session_state.t_my_active], disabled=True)
                    else:
                        played_my = st.selectbox("I played:", st.session_state.t_my_rem)
                        
                with rec_col2:
                    if match_format == "Hero (Last Hero Standing)" and st.session_state.t_opp_active:
                        opp_active_class = get_class_from_deck(st.session_state.t_opp_active)
                        played_opp_c = st.selectbox("Opponent played class:", [opp_active_class], disabled=True)
                        played_arch = st.session_state.t_opp_active
                    else:
                        opp_classes_rem = list(st.session_state.t_opp_status.keys())
                        played_opp_c = st.selectbox("Opponent played class:", opp_classes_rem)
                        played_arch = st.session_state.t_opp_status[played_opp_c]
                    
                if st.session_state.t_opp_status[played_opp_c] == "Unknown":
                    st.warning("⚠️ Reveal their specific archetype above before logging the game result.")
                else:
                    btn_col1, btn_col2 = st.columns(2)
                    with btn_col1:
                        btn_txt = f"🟢 I Won (Remove {played_my})" if match_format == "Legacy (Conquest)" else f"🟢 I Won (Remove {played_arch})"
                        if st.button(btn_txt, use_container_width=True):
                            if match_format == "Legacy (Conquest)":
                                st.session_state.t_my_rem.remove(played_my)
                            else: # Hero
                                del st.session_state.t_opp_status[played_opp_c]
                                st.session_state.t_my_active = played_my
                                st.session_state.t_opp_active = None
                            
                            st.session_state.t_history.append(f"🟢 **WIN:** {played_my} defeated {played_arch}")
                            if 't_nash_roll' in st.session_state: del st.session_state['t_nash_roll']
                            st.rerun()
                            
                    with btn_col2:
                        btn_txt2 = f"🔴 Opponent Won (Remove {played_arch})" if match_format == "Legacy (Conquest)" else f"🔴 Opponent Won (Remove {played_my})"
                        if st.button(btn_txt2, use_container_width=True):
                            if match_format == "Legacy (Conquest)":
                                del st.session_state.t_opp_status[played_opp_c]
                            else: # Hero
                                st.session_state.t_my_rem.remove(played_my)
                                st.session_state.t_opp_active = played_arch
                                st.session_state.t_my_active = None
                                
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
                    
                    my_starting_lineup = st.session_state.t_start_my
                    opp_starting_lineup = list(st.session_state.t_start_opp_revealed.values())

                    clean_logs = [
                        f"Winner: {winner}", f"Final Score: {my_score} - {opp_score}",
                        "-------------------", "STARTING LINEUPS",
                        f"You:      {', '.join(my_starting_lineup)}",
                        f"Opponent: {', '.join(opp_starting_lineup)}",
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
