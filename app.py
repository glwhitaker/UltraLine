import io

import folium
import plotly.graph_objects as go
import streamlit as st
from streamlit_folium import st_folium

from src.races import load_races, race_label

st.set_page_config(
    page_title="UltraLine",
    page_icon="🏔️",
    layout="wide",
    initial_sidebar_state="expanded"
)

races = load_races(confirmed_only=False)
race_labels = [race_label(r) for r in races]


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

    st.subheader("Race")
    selected_label = st.selectbox(
        "Select a race (optional)",
        options=race_labels,
        index=None,
        placeholder="Search races...",
    )
    selected_race = races[race_labels.index(selected_label)] if selected_label else None

    st.subheader("Course")
    gpx_file = st.file_uploader("Upload GPX file", type=["gpx"])

    st.subheader("Runner Profile")
    st.write("Lactate Threshold Pace")
    lt_min_col, lt_sec_col = st.columns(2)
    pace_minutes = lt_min_col.number_input("Minutes", min_value=0, max_value=60, value=0, step=1, key="pace_minutes")
    pace_seconds = lt_sec_col.number_input("Seconds", min_value=0, max_value=60, value=0, step=1, key="pace_seconds")

    st.subheader("Race Goals")
    st.write("Goal Finish Time")
    g_hour_col, g_min_col, g_sec_col = st.columns(3)
    goal_hours   = g_hour_col.number_input("Hours",   min_value=0, max_value=60, value=0, step=1, key="goal_hours")
    goal_minutes = g_min_col.number_input( "Minutes", min_value=0, max_value=60, value=0, step=1, key="goal_minutes")
    goal_seconds = g_sec_col.number_input( "Seconds", min_value=0, max_value=60, value=0, step=1, key="goal_seconds")

    st.divider()
    run_button = st.button("Generate Race Plan", type="primary", use_container_width=True)


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab_course, tab_plan = st.tabs(["Course Overview", "Race Plan"])


# ---------------------------------------------------------------------------
# Course Overview
# ---------------------------------------------------------------------------
with tab_course:
    if gpx_file is None:
        st.info("Upload a GPX file in the sidebar to see the course map and elevation profile.")
    else:
        with st.spinner("Parsing GPX..."):
            try:
                points_df, summary = _parse_gpx_cached(gpx_file.read())
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

        # Route colored by grade
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

        # Mile markers
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

        # Start / finish markers
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

        # ── Combined elevation + grade chart (full width) ─────────────────
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

        # Compute explicit axis ranges so both zeros align at the same pixel height.
        # Strategy: fix the grade range (it naturally spans negative to positive),
        # then extend the elevation range below the data minimum so y=0 sits at the
        # same fractional position on both axes.
        e_lo = float(points_df["elevation_ft"].min())
        e_hi = float(points_df["elevation_ft"].max())
        g_lo = float(grade_df["grade_pct"].min())
        g_hi = float(grade_df["grade_pct"].max())

        # Add headroom to grade range
        g_pad = max(abs(g_lo), abs(g_hi)) * 0.12 + 2
        g_lo -= g_pad
        g_hi += g_pad
        e_hi_padded = e_hi * 1.05

        # Fraction of grade axis below 0
        frac = (0 - g_lo) / (g_hi - g_lo)

        # Extend elevation axis so y=0 sits at the same fraction from the bottom:
        #   (0 - e_lo_aligned) / (e_hi_padded - e_lo_aligned) = frac
        #   → e_lo_aligned = -frac * e_hi_padded / (1 - frac)
        e_lo_aligned = -frac * e_hi_padded / (1 - frac)

        y1_range = [e_lo_aligned, e_hi_padded]
        y2_range = [g_lo, g_hi]

        # Elevation fill as a closed polygon from the profile down to the chart
        # bottom — avoids fill='tozeroy' which anchors to sea level (y=0) and
        # produces a mismatched baseline when the course is above sea level.
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

        # Trace 0 — elevation fill polygon (no hover, not in legend)
        fig.add_trace(go.Scatter(
            x=x_fill,
            y=y_fill,
            fill="toself",
            fillcolor="rgba(79, 195, 247, 0.15)",
            line=dict(width=0, color="rgba(0,0,0,0)"),
            showlegend=False,
            hoverinfo="skip",
            yaxis="y1",
        ))

        # Trace 1 — elevation profile line
        fig.add_trace(go.Scatter(
            x=points_df["distance_mi"],
            y=points_df["elevation_ft"],
            mode="lines",
            line=dict(color="#4fc3f7", width=2),
            hovertemplate="Mile: %{x:.1f}<br>Elevation: %{y:,.0f} ft<extra></extra>",
            name="Elevation",
            yaxis="y1",
        ))

        # Trace 2 — mile marker triangles
        fig.add_trace(go.Scatter(
            x=marker_x,
            y=markers_df["elevation_ft"],
            mode="markers",
            marker=dict(symbol="triangle-up", size=8, color="#4fc3f7"),
            hovertemplate="Mile %{customdata}<br>%{y:,.0f} ft<extra></extra>",
            customdata=markers_df["mile"],
            showlegend=False,
            yaxis="y1",
        ))

        # Trace 3 — grade bars
        fig.add_trace(go.Bar(
            x=grade_df["distance_mi"],
            y=grade_df["grade_pct"],
            marker_color=grade_colors,
            marker_opacity=0.75,
            hovertemplate="Mile: %{x:.2f}<br>Grade: %{y:.1f}%<extra></extra>",
            name="Grade",
            yaxis="y2",
        ))

        fig.update_layout(
            template="plotly_dark",
            height=500,
            margin=dict(l=60, r=60, t=50, b=50),
            paper_bgcolor="#0e1117",
            plot_bgcolor="#0e1117",
            bargap=0,
            xaxis=dict(title="Distance (mi)", showgrid=True, gridcolor="#2a2d35"),
            yaxis=dict(
                title="Elevation (ft)",
                side="left",
                range=y1_range,
                showgrid=True,
                gridcolor="#2a2d35",
                zeroline=True,
                zerolinecolor="#444444",
                zerolinewidth=1,
            ),
            yaxis2=dict(
                title="Grade (%)",
                side="right",
                overlaying="y",
                range=y2_range,
                showgrid=False,
                zeroline=True,
                zerolinecolor="#666666",
                zerolinewidth=1,
            ),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            updatemenus=[dict(
                type="buttons",
                direction="right",
                x=0.0,
                y=1.12,
                xanchor="left",
                yanchor="top",
                bgcolor="#2a2d35",
                bordercolor="#555555",
                borderwidth=1,
                font=dict(color="#e8eaf0", size=12),
                buttons=[
                    dict(
                        label="  Both  ",
                        method="update",
                        args=[
                            {"visible": [True, True, True, True]},
                            {
                                "yaxis.visible": True,
                                "yaxis.range": y1_range,
                                "yaxis2.visible": True,
                                "yaxis2.range": y2_range,
                            },
                        ],
                    ),
                    dict(
                        label="  Elevation  ",
                        method="update",
                        args=[
                            {"visible": [True, True, True, False]},
                            {
                                "yaxis.visible": True,
                                "yaxis.range": y1_range,
                                "yaxis2.visible": False,
                            },
                        ],
                    ),
                    dict(
                        label="  Grade  ",
                        method="update",
                        args=[
                            {"visible": [False, False, False, True]},
                            {
                                "yaxis.visible": False,
                                "yaxis2.visible": True,
                                "yaxis2.range": y2_range,
                            },
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
    st.info("Generate a race plan using the sidebar inputs.")
