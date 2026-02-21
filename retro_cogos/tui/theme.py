"""Fallout Pip-Boy / CRT terminal theme for Retro CogOS."""

from textual.theme import Theme

FALLOUT_THEME = Theme(
    name="fallout",
    primary="#00ff41",
    secondary="#33cc33",
    warning="#ccaa00",
    error="#ff3333",
    success="#00ff41",
    accent="#66ff66",
    foreground="#33cc33",
    background="#0a0f0a",
    surface="#0d1a0d",
    panel="#102010",
    dark=True,
    luminosity_spread=0.12,
    text_alpha=0.92,
    variables={
        "footer-key-foreground": "#00ff41",
        "block-cursor-background": "#00ff41",
        "block-cursor-foreground": "#0a0f0a",
        "block-cursor-text-style": "none",
        "input-selection-background": "#00ff41 25%",
        "button-color-foreground": "#0a0f0a",
        "button-focus-text-style": "reverse",
    },
)

FALLOUT_BANNER = (
    "[dim]══════════════════════════════════════════════[/dim]\n"
    "[bold]  RETRO COGOS // COGNITIVE OPERATING SYSTEM[/bold]\n"
    "[dim]  ROBCO INDUSTRIES (TM) TERMLINK PROTOCOL[/dim]\n"
    "[dim]══════════════════════════════════════════════[/dim]"
)
