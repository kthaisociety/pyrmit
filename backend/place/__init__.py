"""
Place lookup for the chat's map pin: which property, plans, protected areas, national interests and ancient
remains cover a point, from Swedish open geodata. No LLM: the profile comes from registers, is shown to the user
as the place card and is given to the agent as context (CHAT_MODE=agent).

    python -m place.fetch --kommun 0380   # snapshot the area layers of a pilot kommun -> data/geo/<code>/

Area layers (plans, land-use zones, protected areas, national interests) are dated snapshots per kommun (fast,
reproducible for the evals); the property and the ancient remains are looked up live at the point.
"""
