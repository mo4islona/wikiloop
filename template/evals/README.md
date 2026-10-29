# Trigger evals

Each case is one real prompt (from a session, internal names removed) and the skill the agent
must load first. `python3 core/bin/wikiloop evals` runs them; the core adds its negative cases,
prompts no wiki skill fits. A failing case is fixed in the skill's `description`, never by a
change to the prompt. Add a case when a real session should have loaded a skill and did not.
