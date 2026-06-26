"""Shared pipeline view helper — renders a completed run."""
import streamlit as st


def render_pipeline_view(run):
    """Render a completed pipeline run (used from Applications page)."""
    from pages.apply import _render_decision
    _render_decision(run)
