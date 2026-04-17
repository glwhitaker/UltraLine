import streamlit as st

st.set_page_config(
    page_title="UltraLine",
    page_icon="🏔️",
    layout="wide",
    initial_sidebar_state="expanded"
)

with st.sidebar:
    st.title("UltraLine")
    st.caption("Race execution optimizer")

    st.divider()

    st.subheader("Course")
    gpx_file = st.file_uploader("Upload GPX file", type=["gpx"])

    st.subheader("Runner Profile")
    st.write("Lactate Threshold Pace:")
    lt_min_col, lt_sec_col = st.columns(2)
    pace_minutes    = lt_min_col.number_input("Minutes", min_value=0, max_value=60, value=0, step=1, key="pace_minutes")
    pace_seconds    = lt_sec_col.number_input("Seconds", min_value=0, max_value=60, value=0, step=1, key="pace_seconds")

    st.subheader("Race Goals")
    st.write("Goal Finish Time:")
    g_hour_col, g_min_col, g_sec_col = st.columns(3)
    goal_hours      = g_hour_col.number_input("Hours", min_value=0, max_value=60, value=0, step=1, key="goal_hours")
    goal_minutes    = g_min_col.number_input("Minutes", min_value=0, max_value=60, value=0, step=1, key="goal_minutes")
    goal_seconds    = g_sec_col.number_input("Seconds", min_value=0, max_value=60, value=0, step=1, key="goal_seconds")

    st.divider()
    run_button = st.button("Generate Race Plan", type="primary", use_container_width=True)


tab_course, tab_plan = st.tabs([
    "Course Overview",
    "Race Plan"
])

with tab_course:
    st.header("Course Overview")
    if gpx_file is None:
        st.info("Upload a GPX file in the sidebar to see the course map and elevation profile.")
    else:
        st.warning("GPX parsing coming soon.")

with tab_plan:
    st.header("Race Plan")
    st.info("Generate a race plan using the sidebar inputs.")
