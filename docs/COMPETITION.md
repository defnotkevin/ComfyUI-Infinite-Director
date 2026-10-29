# Competition demonstration

Position the entry as **a persistent scene you can direct**, with open-weight Qwen
references and LTX video. The distinctive behavior is the combination of a fixed
performance timeline, editable camera coverage, dependency-aware regeneration, and
reusable takes—not an assertion that arbitrary unseen motion is reconstructed exactly.

Suggested demonstration with actual model outputs:

1. Show the original recording with its unmodified speech.
2. Show Other References, then the agent-generated bible, character/prop sheets, and camera storyboard.
3. Play a short edit with a frontal shot, three-quarter view, and a deliberate prop insert.
4. Change one camera setup in the studio and render that shot only.
5. Compare two takes, approve one, and export again. Show the unchanged neighboring shots.
6. Explain the bridge node, local Qwen/LTX graphs, and original master-audio assembly.

An inside-the-cup reference is supported as an authored shot, but should be shown only
with a genuine model result that survives review. Stage it during a pause or as a
voiceover insert; avoid promising physically accurate speaking while drinking.

The synthetic CPU test harness is for software verification and must not be presented
as generative-model output. The implementation has no measured GPU performance yet.
Before submission, capture real Qwen/LTX runs, record model versions/settings and hardware,
and verify the actual install on the demonstration host.

The organizer's page states that app code must have an open-source license and setup
instructions, that Open Weights Only excludes partner nodes and closed APIs, and that
LTX must be the core video model for its VFX bonus. Check the official page for current
submission details: https://comfy.org/open-source-higgsfield/

This repository includes MIT-licensed application code, attributed LTX workflow
licensing, setup instructions, editable workflows, and automated CPU tests. It has not
been published or submitted to the competition by this implementation task.
