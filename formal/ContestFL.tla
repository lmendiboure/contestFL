------------------------------- MODULE ContestFL -------------------------------
EXTENDS Naturals, FiniteSets, TLC

CONSTANTS Checkpoints, ValidCheckpoints, RetryBudget, Coverage, NoCheckpoint

ASSUME /\ Checkpoints # {}
       /\ ValidCheckpoints # {}
       /\ ValidCheckpoints \subseteq Checkpoints
       /\ NoCheckpoint \notin Checkpoints
       /\ RetryBudget \in Nat
       /\ Coverage \in BOOLEAN

Phases == {"Challenge", "Resolving", "Ready", "Finalized", "Aborted"}
TerminalPhases == {"Finalized", "Aborted"}
ChallengeStates == {"None", "Valid", "False"}

VARIABLES phase,
          epoch,
          retries,
          current,
          currentValid,
          currentCertified,
          currentProvisional,
          challenge,
          superseded,
          finalCheckpoint,
          finalizationCount

vars == <<phase, epoch, retries, current, currentValid, currentCertified,
          currentProvisional, challenge, superseded, finalCheckpoint,
          finalizationCount>>

TypeOK ==
    /\ phase \in Phases
    /\ epoch \in Nat
    /\ retries \in 0..RetryBudget
    /\ current \in Checkpoints
    /\ currentValid \in BOOLEAN
    /\ currentCertified \in BOOLEAN
    /\ currentProvisional \in BOOLEAN
    /\ challenge \in ChallengeStates
    /\ superseded \subseteq Checkpoints
    /\ finalCheckpoint \in Checkpoints \cup {NoCheckpoint}
    /\ finalizationCount \in 0..1

Init ==
    /\ phase = "Challenge"
    /\ epoch = 1
    /\ retries = 0
    /\ current \in Checkpoints
    /\ currentValid = (current \in ValidCheckpoints)
    /\ currentCertified = FALSE
    /\ currentProvisional = TRUE
    /\ challenge = "None"
    /\ superseded = {}
    /\ finalCheckpoint = NoCheckpoint
    /\ finalizationCount = 0

OpenInvalidChallenge ==
    /\ phase = "Challenge"
    /\ challenge = "None"
    /\ ~currentValid
    /\ Coverage
    /\ challenge' = "Valid"
    /\ UNCHANGED <<phase, epoch, retries, current, currentValid,
                    currentCertified, currentProvisional, superseded,
                    finalCheckpoint, finalizationCount>>

OpenFalseChallenge ==
    /\ phase = "Challenge"
    /\ challenge = "None"
    /\ currentValid
    /\ challenge' = "False"
    /\ UNCHANGED <<phase, epoch, retries, current, currentValid,
                    currentCertified, currentProvisional, superseded,
                    finalCheckpoint, finalizationCount>>

CloseChallengeWindow ==
    /\ phase = "Challenge"
    /\ challenge = "None"
    /\ (currentValid \/ ~Coverage)
    /\ phase' = "Ready"
    /\ currentProvisional' = FALSE
    /\ UNCHANGED <<epoch, retries, current, currentValid, currentCertified,
                    challenge, superseded, finalCheckpoint,
                    finalizationCount>>

ResolveValidChallenge ==
    /\ phase = "Challenge"
    /\ challenge = "Valid"
    /\ phase' = "Resolving"
    /\ challenge' = "None"
    /\ superseded' = superseded \cup {current}
    /\ currentProvisional' = FALSE
    /\ UNCHANGED <<epoch, retries, current, currentValid, currentCertified,
                    finalCheckpoint, finalizationCount>>

ResolveFalseChallenge ==
    /\ phase = "Challenge"
    /\ challenge = "False"
    /\ phase' = "Ready"
    /\ challenge' = "None"
    /\ currentProvisional' = FALSE
    /\ UNCHANGED <<epoch, retries, current, currentValid, currentCertified,
                    superseded, finalCheckpoint, finalizationCount>>

PublishReplacement ==
    /\ phase = "Resolving"
    /\ retries < RetryBudget
    /\ \E cp \in (Checkpoints \ superseded):
          /\ phase' = "Challenge"
          /\ epoch' = epoch + 1
          /\ retries' = retries + 1
          /\ current' = cp
          /\ currentValid' = (cp \in ValidCheckpoints)
          /\ currentCertified' = FALSE
          /\ currentProvisional' = TRUE
          /\ challenge' = "None"
          /\ UNCHANGED <<superseded, finalCheckpoint,
                          finalizationCount>>

PublishCertifiedFallback ==
    /\ phase = "Resolving"
    /\ retries >= RetryBudget
    /\ \E cp \in (ValidCheckpoints \ superseded):
          /\ phase' = "Ready"
          /\ epoch' = epoch + 1
          /\ current' = cp
          /\ currentValid' = TRUE
          /\ currentCertified' = TRUE
          /\ currentProvisional' = FALSE
          /\ challenge' = "None"
          /\ UNCHANGED <<retries, superseded, finalCheckpoint,
                          finalizationCount>>

AbortRecovery ==
    /\ phase = "Resolving"
    /\ phase' = "Aborted"
    /\ challenge' = "None"
    /\ currentProvisional' = FALSE
    /\ UNCHANGED <<epoch, retries, current, currentValid,
                    currentCertified, superseded, finalCheckpoint,
                    finalizationCount>>

Finalize ==
    /\ phase = "Ready"
    /\ challenge = "None"
    /\ ~currentProvisional
    /\ phase' = "Finalized"
    /\ finalCheckpoint' = current
    /\ finalizationCount' = finalizationCount + 1
    /\ UNCHANGED <<epoch, retries, current, currentValid,
                    currentCertified, currentProvisional, challenge,
                    superseded>>

Next ==
    \/ OpenInvalidChallenge
    \/ OpenFalseChallenge
    \/ CloseChallengeWindow
    \/ ResolveValidChallenge
    \/ ResolveFalseChallenge
    \/ PublishReplacement
    \/ PublishCertifiedFallback
    \/ AbortRecovery
    \/ Finalize

Spec == Init /\ [][Next]_vars /\ WF_vars(Next)

RetryBound == retries <= RetryBudget
AtMostOneFinalization == finalizationCount <= 1
NoSupersededFinalization ==
    phase = "Finalized" => finalCheckpoint \notin superseded
NoProvisionalFinalization ==
    phase = "Finalized" => ~currentProvisional
CanonicalFinalization ==
    phase = "Finalized" => finalCheckpoint = current
PolicyValidityUnderCoverage ==
    (Coverage /\ phase = "Finalized") => finalCheckpoint \in ValidCheckpoints
TerminalHasNoOpenChallenge ==
    phase \in TerminalPhases => challenge = "None"

Termination == <>(phase \in TerminalPhases)

=============================================================================
