# 20. If the kill switch cannot be checked, nothing is allowed

**What this proves:** when the control plane is unreachable, the policy service denies everything rather than assuming no switch is tripped. The run also exposed, and led to fixing, a cascade where that outage froze an innocent agent after recovery.

## Background
`kill_switch_blocks()` in `infra/policy-service/app/main.py` treats any HTTP error talking to the control plane as `kill switch state unavailable (...); failing closed`. Separately, the control plane's watchdog (every 15 s) trips an agent switch when one agent collects `DENIAL_TRIP_COUNT=5` denials within `DENIAL_TRIP_WINDOW_SECONDS=600` (scenario 21).

## Steps
1. `infra/scripts/compose.sh stop custodian-control-plane`
2. Authorize an action that is normally allowed (the extraction agent's `ExtractInvoice`)
3. `infra/scripts/compose.sh up -d --wait custodian-control-plane` and authorize the same action again

## What you'll see
Step 2:
```
 Container custodian-custodian-control-plane-1 Stopped
HTTP 200 deny {'kill_switch': 'blocked', 'cedar': 'allow', 'temporal': 'allow'} ['kill switch state unavailable (ConnectError); failing closed', 'cedar: extraction-agent-extracts']
```
Step 3, on the first run:
```
 Container custodian-custodian-control-plane-1 Healthy
HTTP 200 deny {'kill_switch': 'blocked', 'cedar': 'allow', 'temporal': 'allow'} ['kill switch: agent extraction: 6 policy denials in 600s', 'cedar: extraction-agent-extracts']
```

## The cascade, and the fix
The second deny was a real bug. When the control plane came back, its first watchdog pass counted the extraction agent's recent denials. There were six: three it had genuinely earned (scenario 13's deliberate requests), and three that were not its fault. Those were blocks by the global kill switch in scenario 19, and the fail-closed deny in step 2. The watchdog tripped the agent, so an infrastructure outage turned into a frozen agent once the infrastructure recovered.

The fix:
- `policy_decisions` now stores each decision's per-check verdicts (`checks`).
- The repeated-denial trigger counts only denials where `cedar` or `temporal` said deny (`custodian-control-plane/app/watchdog.py`).

After the fix, stopping and restarting the control plane leaves the agent's switch untouched.

## What this actually teaches
- **Fail-closed is easy to state and to show.** Step 2 is all it takes.
- **The interactions are harder.** A fail-closed denial is a signal about the platform, not about the agent. Any automation that reacts to denials has to be able to tell the two apart, or an outage of the safety system becomes an outage of the thing it protects. Recording why each check decided, not only the overall decision, is what made that distinction possible.
