import io

import folium
import plotly.graph_objects as go
import streamlit as st
from streamlit_folium import st_folium

from src.races import load_curated_races, curated_race_label

st.set_page_config(
    page_title="UltraLine",
    page_icon="🏔️",
    layout="wide",
    initial_sidebar_state="expanded"
)

curated_races = load_curated_races()
curated_labels = [curated_race_label(r) for r in curated_races]


@st.cache_data
def _parse_gpx_cached(file_bytes: bytes):
    from src.course import parse_gpx
    return parse_gpx(io.BytesIO(file_bytes))


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.title("UltraLine")
    st.caption("Race execution optimizer")

    st.divider()

    # ── Past Race (calibration anchor) ──────────────────────────────────────
    st.subheader("Your Past Race")
    st.caption("Used to calibrate your fitness level.")

    past_gpx_file = st.file_uploader(
        "GPX file for a race you've completed",
        type=["gpx"],
        key="past_gpx",
    )

    st.write("Your finish time")
    p_h_col, p_m_col, p_s_col = st.columns(3)
    past_hours   = p_h_col.number_input("Hours",   min_value=0, max_value=999, value=0, step=1, key="past_hours")
    past_minutes = p_m_col.number_input("Min",     min_value=0, max_value=59,  value=0, step=1, key="past_minutes")
    past_seconds = p_s_col.number_input("Sec",     min_value=0, max_value=59,  value=0, step=1, key="past_seconds")

    past_finish_seconds = past_hours * 3600 + past_minutes * 60 + past_seconds

    st.divider()

    # ── About You (optional) ─────────────────────────────────────────────────
    st.subheader("About You")
    st.caption("Optional — improves estimate accuracy.")

    gender = st.selectbox(
        "Gender",
        options=["Male", "Female"],
        index=None,
        placeholder="Select…",
        key="gender",
    )

    birth_year = st.number_input(
        "Birth year",
        min_value=1920,
        max_value=2010,
        value=None,
        step=1,
        placeholder="e.g. 1985",
        key="birth_year",
    )

    st.divider()

    # ── Target Race ──────────────────────────────────────────────────────────
    st.subheader("Target Race")
    st.caption("The race you want to estimate.")

    target_mode = st.radio(
        "How would you like to specify the target race?",
        options=["Upload GPX", "Search race list", "Enter course details"],
        index=0,
        key="target_mode",
        label_visibility="collapsed",
    )

    selected_race = None
    target_gpx_file = None
    manual_inputs = None

    MONTH_NAMES = [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December"
    ]
    SURFACES = ["Road", "Gravel", "Trail", "Technical"]

    if target_mode == "Upload GPX":
        target_gpx_file = st.file_uploader(
            "GPX file for the target race",
            type=["gpx"],
            key="target_gpx_upload",
        )

    elif target_mode == "Search race list":
        selected_label = st.selectbox(
            "Select a race",
            options=curated_labels,
            index=None,
            placeholder="Search races…",
            key="race_select",
        )
        selected_race = curated_races[curated_labels.index(selected_label)] if selected_label else None

        # Write prefill values directly to session state whenever the selection
        # changes. This is the only reliable way to update already-rendered
        # widgets in Streamlit — the `value` param is ignored after first render.
        curr_name = selected_race["name"] if selected_race else None
        if curr_name != st.session_state.get("_prefilled_race_name"):
            st.session_state["_prefilled_race_name"] = curr_name
            if selected_race:
                st.session_state["list_dist"]    = float(selected_race["distance_mi"])
                st.session_state["list_gain"]    = int(selected_race["elevation_gain_ft"])
                st.session_state["list_loss"]    = int(selected_race["elevation_loss_ft"])
                st.session_state["list_surface"] = selected_race["surface"]
                st.session_state["list_month"]   = selected_race["typical_month"]
            else:
                for k in ["list_dist", "list_gain", "list_loss", "list_surface", "list_month"]:
                    st.session_state.pop(k, None)

        st.caption("Course details — adjust if your race edition differs.")
        t_dist = st.number_input(
            "Distance (mi)", min_value=1.0, max_value=500.0, step=0.1,
            value=None, placeholder="e.g. 100.0", key="list_dist"
        )
        t_gain = st.number_input(
            "Elevation gain (ft)", min_value=0, max_value=200000, step=100,
            value=None, placeholder="e.g. 18000", key="list_gain"
        )
        t_loss = st.number_input(
            "Elevation loss (ft)", min_value=0, max_value=200000, step=100,
            value=None, placeholder="e.g. 18000", key="list_loss"
        )
        t_surface = st.selectbox(
            "Surface type", options=SURFACES,
            index=None, key="list_surface"
        )
        t_month = st.selectbox(
            "Month of race", options=list(range(1, 13)),
            index=None, format_func=lambda m: MONTH_NAMES[m - 1],
            placeholder="Select month…", key="list_month"
        )
        manual_inputs = {
            "distance_mi": t_dist,
            "gain_ft":     t_gain,
            "loss_ft":     t_loss,
            "surface":     t_surface,
            "month":       t_month,
        }

    else:  # Enter course details
        t_dist = st.number_input(
            "Distance (mi)", min_value=1.0, max_value=500.0,
            value=None, step=0.1, placeholder="e.g. 100.0", key="manual_dist"
        )
        t_gain = st.number_input(
            "Elevation gain (ft)", min_value=0, max_value=200000,
            value=None, step=100, placeholder="e.g. 18000", key="manual_gain"
        )
        t_loss = st.number_input(
            "Elevation loss (ft)", min_value=0, max_value=200000,
            value=None, step=100, placeholder="e.g. 18000", key="manual_loss"
        )
        t_surface = st.selectbox(
            "Surface type", options=SURFACES,
            index=None, placeholder="Select surface…", key="manual_surface"
        )
        t_month = st.selectbox(
            "Month of race", options=list(range(1, 13)),
            index=None, format_func=lambda m: MONTH_NAMES[m - 1],
            placeholder="Select month…", key="manual_month"
        )
        manual_inputs = {
            "distance_mi": t_dist,
            "gain_ft":     t_gain,
            "loss_ft":     t_loss,
            "surface":     t_surface,
            "month":       t_month,
        }

    st.divider()
    run_button = st.button("Estimate Finish Time", type="primary", use_container_width=True)


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab_course, tab_plan = st.tabs(["Course Overview", "Race Plan"])


# ---------------------------------------------------------------------------
# Course Overview — shows target race GPX when available
# ---------------------------------------------------------------------------
with tab_course:
    if target_gpx_file is None:
        if target_mode == "Enter course details":
            st.info("Course map is not available in manual entry mode. Upload a GPX file to see the map and elevation profile.")
        else:
            st.info("Upload a GPX file for the target race to see the course map and elevation profile.")
    else:
        with st.spinner("Parsing GPX…"):
            try:
                points_df, summary = _parse_gpx_cached(target_gpx_file.read())
            except Exception as e:
                st.error(f"Could not parse GPX file: {e}")
                st.stop()

        from src.course import downsample, mile_markers
        map_df     = downsample(points_df, max_points=2000)
        grade_df   = downsample(points_df, max_points=300)
        markers_df = mile_markers(points_df)

        # ── Stats strip ──────────────────────────────────────────────────
        st.subheader("Course Stats")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Distance",   f"{summary['total_distance_mi']:.1f} mi")
        c2.metric("Elevation Gain",   f"+{summary['cumulative_gain_ft']:,.0f} ft")
        c3.metric("Elevation Loss",   f"-{summary['cumulative_loss_ft']:,.0f} ft")
        c4.metric("Max Grade",        f"+{summary['max_uphill_grade_pct']:.0f}% / {summary['max_downhill_grade_pct']:.0f}%")

        c5, c6, c7, c8 = st.columns(4)
        c5.metric("Min Elevation",    f"{summary['min_elevation_ft']:,.0f} ft")
        c6.metric("Max Elevation",    f"{summary['max_elevation_ft']:,.0f} ft")
        c7.metric("Up / Flat / Down", f"{summary['pct_uphill']}% / {summary['pct_flat']}% / {summary['pct_downhill']}%")
        c8.metric("Longest Climb",    f"{summary['longest_climb_distance_mi']:.1f} mi / +{summary['longest_climb_gain_ft']:,.0f} ft")

        st.divider()

        # ── Course Map (full width) ───────────────────────────────────────
        st.subheader("Course Map")
        m = folium.Map(
            tiles="https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
            attr="CartoDB DarkMatter",
        )

        coords     = list(zip(map_df["lat"], map_df["lon"]))
        grade_vals = map_df["grade_pct"].tolist()
        folium.ColorLine(
            coords,
            colors=grade_vals,
            colormap=["#4575b4", "#74add1", "#555555", "#f46d43", "#d73027"],
            vmin=-15,
            vmax=15,
            weight=5,
        ).add_to(m)

        for _, row in markers_df.iterrows():
            folium.CircleMarker(
                location=[row["lat"], row["lon"]],
                radius=4,
                color="#4fc3f7",
                fill=True,
                fill_color="#0e1117",
                fill_opacity=0.9,
                popup=folium.Popup(f"Mile {int(row['mile'])} — {row['elevation_ft']:,.0f} ft", max_width=150),
                tooltip=f"Mile {int(row['mile'])}",
            ).add_to(m)

        folium.Marker(
            location=[points_df["lat"].iloc[0], points_df["lon"].iloc[0]],
            tooltip="Start",
            icon=folium.Icon(icon="play", prefix="fa", color="green"),
        ).add_to(m)
        folium.Marker(
            location=[points_df["lat"].iloc[-1], points_df["lon"].iloc[-1]],
            tooltip="Finish",
            icon=folium.Icon(icon="stop", prefix="fa", color="red"),
        ).add_to(m)

        m.fit_bounds([
            [points_df["lat"].min(), points_df["lon"].min()],
            [points_df["lat"].max(), points_df["lon"].max()],
        ])
        st_folium(m, use_container_width=True, height=500)

        st.divider()

        # ── Elevation + grade chart ───────────────────────────────────────
        st.subheader("Elevation & Grade Profile")

        marker_x = markers_df.apply(
            lambda r: points_df.loc[(points_df["distance_mi"] - r["mile"]).abs().idxmin(), "distance_mi"],
            axis=1,
        )

        def _grade_color(g: float) -> str:
            if   g >  20: return "#ff1744"
            elif g >  10: return "#ff6d00"
            elif g >   1: return "#ffd740"
            elif g >= -1: return "#90a4ae"
            elif g >= -10: return "#40c4ff"
            elif g >= -20: return "#0091ea"
            else:          return "#01579b"

        grade_colors = [_grade_color(g) for g in grade_df["grade_pct"]]

        e_lo = float(points_df["elevation_ft"].min())
        e_hi = float(points_df["elevation_ft"].max())
        g_lo = float(grade_df["grade_pct"].min())
        g_hi = float(grade_df["grade_pct"].max())

        g_pad = max(abs(g_lo), abs(g_hi)) * 0.12 + 2
        g_lo -= g_pad
        g_hi += g_pad
        e_hi_padded = e_hi * 1.05

        frac = (0 - g_lo) / (g_hi - g_lo)
        e_lo_aligned = -frac * e_hi_padded / (1 - frac)

        y1_range = [e_lo_aligned, e_hi_padded]
        y2_range = [g_lo, g_hi]

        x_fill = (
            list(points_df["distance_mi"])
            + [float(points_df["distance_mi"].iloc[-1]),
               float(points_df["distance_mi"].iloc[0])]
        )
        y_fill = (
            list(points_df["elevation_ft"])
            + [e_lo_aligned, e_lo_aligned]
        )

        fig = go.Figure()

        fig.add_trace(go.Scatter(
            x=x_fill, y=y_fill,
            fill="toself",
            fillcolor="rgba(79, 195, 247, 0.15)",
            line=dict(width=0, color="rgba(0,0,0,0)"),
            showlegend=False, hoverinfo="skip", yaxis="y1",
        ))
        fig.add_trace(go.Scatter(
            x=points_df["distance_mi"], y=points_df["elevation_ft"],
            mode="lines", line=dict(color="#4fc3f7", width=2),
            hovertemplate="Mile: %{x:.1f}<br>Elevation: %{y:,.0f} ft<extra></extra>",
            name="Elevation", yaxis="y1",
        ))
        fig.add_trace(go.Scatter(
            x=marker_x, y=markers_df["elevation_ft"],
            mode="markers",
            marker=dict(symbol="triangle-up", size=8, color="#4fc3f7"),
            hovertemplate="Mile %{customdata}<br>%{y:,.0f} ft<extra></extra>",
            customdata=markers_df["mile"],
            showlegend=False, yaxis="y1",
        ))
        fig.add_trace(go.Bar(
            x=grade_df["distance_mi"], y=grade_df["grade_pct"],
            marker_color=grade_colors, marker_opacity=0.75,
            hovertemplate="Mile: %{x:.2f}<br>Grade: %{y:.1f}%<extra></extra>",
            name="Grade", yaxis="y2",
        ))

        fig.update_layout(
            template="plotly_dark", height=500,
            margin=dict(l=60, r=60, t=50, b=50),
            paper_bgcolor="#0e1117", plot_bgcolor="#0e1117",
            bargap=0,
            xaxis=dict(title="Distance (mi)", showgrid=True, gridcolor="#2a2d35"),
            yaxis=dict(
                title="Elevation (ft)", side="left", range=y1_range,
                showgrid=True, gridcolor="#2a2d35",
                zeroline=True, zerolinecolor="#444444", zerolinewidth=1,
            ),
            yaxis2=dict(
                title="Grade (%)", side="right", overlaying="y", range=y2_range,
                showgrid=False, zeroline=True, zerolinecolor="#666666", zerolinewidth=1,
            ),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            updatemenus=[dict(
                type="buttons", direction="right",
                x=0.0, y=1.12, xanchor="left", yanchor="top",
                bgcolor="#2a2d35", bordercolor="#555555", borderwidth=1,
                font=dict(color="#e8eaf0", size=12),
                buttons=[
                    dict(
                        label="  Both  ", method="update",
                        args=[
                            {"visible": [True, True, True, True]},
                            {"yaxis.visible": True, "yaxis.range": y1_range,
                             "yaxis2.visible": True, "yaxis2.range": y2_range},
                        ],
                    ),
                    dict(
                        label="  Elevation  ", method="update",
                        args=[
                            {"visible": [True, True, True, False]},
                            {"yaxis.visible": True, "yaxis.range": y1_range,
                             "yaxis2.visible": False},
                        ],
                    ),
                    dict(
                        label="  Grade  ", method="update",
                        args=[
                            {"visible": [False, False, False, True]},
                            {"yaxis.visible": False, "yaxis2.visible": True,
                             "yaxis2.range": y2_range},
                        ],
                    ),
                ],
            )],
        )

        st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------------------------
# Race Plan
# ---------------------------------------------------------------------------
with tab_plan:
    st.header("Race Plan")

    if run_button:
        # Validate required inputs
        missing = []
        if past_gpx_file is None:
            missing.append("GPX file for your past race")
        if past_finish_seconds == 0:
            missing.append("your finish time for the past race")
        if target_mode == "Upload GPX" and target_gpx_file is None:
            missing.append("a GPX file for the target race")
        if target_mode in ("Search race list", "Enter course details") and not all([
            manual_inputs["distance_mi"], manual_inputs["surface"], manual_inputs["month"]
        ]):
            missing.append("complete course details for the target race")

        if missing:
            st.warning("Please provide: " + "; ".join(missing) + ".")
        else:
            st.info("Estimation model coming in a future step. Inputs look good — ready to wire up.")
    else:
        st.info("Fill in your past race and target race in the sidebar, then click **Estimate Finish Time**.")
