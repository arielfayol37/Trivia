from __future__ import annotations


def sample_quiz_document(prompt: str, source_text: str = "") -> dict:
    topic = prompt.strip() or "general science"
    return {
        "title": f"{topic[:80]} — AI Draft",
        "description": "A first-pass generated quiz draft. Review and refine before publishing.",
        "category": _sample_category(topic),
        "topic": topic,
        "difficulty": "hard" if "hard" in topic.lower() else "medium",
        "status": "draft",
        "visibility": "private",
        "anticheat_strictness": "friendly",
        "source_material": {
            "kind": "text" if source_text else "topic",
            "content": source_text or topic,
        },
        "rounds": [
            {
                "type": "sync_open",
                "order": 1,
                "config": {
                    "answer_timeout_s": 25,
                    "points_per_question": 10,
                    "speed_bonus": False,
                },
                "questions": [
                    {
                        "order": 1,
                        "prompt_blocks": [
                            {
                                "type": "text",
                                "text": "State the physical quantity described by the time-dependent Schrodinger equation.",
                            },
                            {
                                "type": "math",
                                "latex": "i\\hbar\\frac{\\partial}{\\partial t}\\Psi(t)=\\hat{H}\\Psi(t)",
                            },
                        ],
                        "answer_widget": {
                            "type": "text_input",
                            "placeholder": "Type the concept, not the full derivation",
                        },
                        "canonical_answer": "time evolution of the wavefunction",
                        "acceptable_answers": [
                            "time evolution of the wavefunction",
                            "evolution of a quantum state over time",
                            "how the wavefunction changes with time",
                            "time evolution of a quantum system",
                        ],
                        "judge_mode": "fuzzy",
                    },
                    {
                        "order": 2,
                        "prompt_blocks": [
                            {
                                "type": "text",
                                "text": "In one sentence, what role does the Hamiltonian operator play in the Schrodinger equation?",
                            }
                        ],
                        "answer_widget": {"type": "text_input"},
                        "canonical_answer": "it generates the time evolution and represents total energy",
                        "acceptable_answers": [
                            "it generates time evolution",
                            "the hamiltonian generates time evolution",
                            "it represents total energy",
                            "energy operator",
                        ],
                        "judge_mode": "llm",
                        "judge_config": {"strictness": "lenient"},
                    },
                ],
            },
            {
                "type": "list_race",
                "order": 2,
                "config": {
                    "prompt": "Name the common quantum numbers for an electron in an atom.",
                    "time_limit_s": 90,
                    "items": [
                        {
                            "canonical": "principal quantum number",
                            "acceptable": ["principal", "n", "principal quantum number"],
                        },
                        {
                            "canonical": "azimuthal quantum number",
                            "acceptable": [
                                "azimuthal",
                                "orbital angular momentum",
                                "l",
                                "azimuthal quantum number",
                            ],
                        },
                        {
                            "canonical": "magnetic quantum number",
                            "acceptable": ["magnetic", "m", "ml", "magnetic quantum number"],
                        },
                        {
                            "canonical": "spin quantum number",
                            "acceptable": ["spin", "ms", "spin quantum number"],
                        },
                    ],
                },
                "questions": [],
            },
        ],
    }


def _sample_category(topic: str) -> str:
    text = topic.lower()
    if any(keyword in text for keyword in ["physics", "quantum", "science", "chemistry", "biology"]):
        return "science"
    if any(keyword in text for keyword in ["geography", "flag", "country", "capital", "map", "cameroon"]):
        return "geography"
    if any(keyword in text for keyword in ["baseball", "mlb", "stadium", "sports", "nba", "nfl"]):
        return "sports"
    if any(keyword in text for keyword in ["game of thrones", "movie", "tv", "show"]):
        return "tv"
    if "history" in text:
        return "history"
    return "general"
