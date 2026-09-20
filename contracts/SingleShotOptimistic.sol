// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @notice Representative single-shot optimistic verification baseline.
/// @dev One challenged state can be replaced once, but the replacement is
///      terminal: it receives no fresh challenge window, has no retry lineage,
///      and has no resolver fallback. The contract intentionally exposes the
///      semantic gap addressed by ContestFL's correction closure.
contract SingleShotOptimistic {
    enum Phase { NONE, SUBMIT, CHALLENGE, RESOLVING, READY, FINALIZED, ABORTED }
    enum DecisionKind { ADMIT, INCLUDE, AGGREGATE }
    enum ChallengeOutcome { OPEN, UPHELD, REVISED, DISMISSED }

    struct Round {
        uint32 expectedSubmissions;
        uint32 submissionCount;
        uint32 decisionCount;
        uint32 challengeBlocks;
        uint32 responseBlocks;
        uint32 openChallenges;
        uint64 challengeEndBlock;
        Phase phase;
        bool statePublished;
        bool needsReplacement;
        bytes32 submissionRoot;
        bytes32 admittedRoot;
        bytes32 aggregateInputRoot;
        bytes32 checkpointHash;
    }

    struct Challenge {
        uint256 roundId;
        DecisionKind kind;
        bytes32 clientId;
        uint8 claimedState;
        bytes32 evidenceHash;
        bytes32 certificateHash;
        uint64 responseDeadline;
        ChallengeOutcome outcome;
    }

    address public immutable coordinator;
    address public immutable resolver;
    uint256 public nextChallengeId = 1;

    mapping(uint256 => Round) public rounds;
    mapping(uint256 => mapping(bytes32 => bytes32)) public submissionHash;
    mapping(uint256 => mapping(bytes32 => uint8)) public decisionState;
    mapping(uint256 => Challenge) public challenges;

    event RoundOpened(uint256 indexed roundId, uint32 expectedSubmissions);
    event SubmissionReceived(uint256 indexed roundId, bytes32 indexed clientId, bytes32 updateHash);
    event DecisionPublished(uint256 indexed roundId, bytes32 indexed clientId, uint8 state);
    event StatePublished(uint256 indexed roundId, bytes32 checkpointHash, uint64 challengeEndBlock);
    event ChallengeOpened(uint256 indexed challengeId, uint256 indexed roundId, DecisionKind kind, bytes32 clientId);
    event ChallengeResolved(uint256 indexed challengeId, ChallengeOutcome outcome, bytes32 certificateHash);
    event TerminalReplacementPublished(uint256 indexed roundId, bytes32 checkpointHash);
    event RoundFinalized(uint256 indexed roundId, bytes32 checkpointHash);

    error CoordinatorOnly();
    error ResolverOnly();
    error InvalidState();
    error InvalidArgument();
    error MissingSubmission();
    error DuplicateSubmission();
    error DuplicateDecision();
    error ChallengeWindowClosed();
    error ChallengeWindowOpen();
    error ResponseDeadlineExpired();
    error OpenChallengesRemain();

    modifier onlyCoordinator() {
        if (msg.sender != coordinator) revert CoordinatorOnly();
        _;
    }

    modifier onlyResolver() {
        if (msg.sender != resolver) revert ResolverOnly();
        _;
    }

    constructor(address initialCoordinator, address initialResolver) {
        if (initialCoordinator == address(0) || initialResolver == address(0)) revert InvalidArgument();
        coordinator = initialCoordinator;
        resolver = initialResolver;
    }

    function openRound(
        uint256 roundId,
        uint32 expectedSubmissions,
        uint32 challengeBlocks,
        uint32 responseBlocks
    ) external onlyCoordinator {
        Round storage r = rounds[roundId];
        if (r.phase != Phase.NONE) revert InvalidState();
        if (expectedSubmissions == 0 || challengeBlocks == 0 || responseBlocks == 0) revert InvalidArgument();
        r.expectedSubmissions = expectedSubmissions;
        r.challengeBlocks = challengeBlocks;
        r.responseBlocks = responseBlocks;
        r.phase = Phase.SUBMIT;
        emit RoundOpened(roundId, expectedSubmissions);
    }

    function submit(uint256 roundId, bytes32 clientId, bytes32 updateHash) external {
        Round storage r = rounds[roundId];
        if (r.phase != Phase.SUBMIT) revert InvalidState();
        if (clientId == bytes32(0) || updateHash == bytes32(0)) revert InvalidArgument();
        if (submissionHash[roundId][clientId] != bytes32(0)) revert DuplicateSubmission();
        if (r.submissionCount >= r.expectedSubmissions) revert InvalidArgument();
        submissionHash[roundId][clientId] = updateHash;
        unchecked { r.submissionCount += 1; }
        emit SubmissionReceived(roundId, clientId, updateHash);
    }

    function publishDecisions(
        uint256 roundId,
        bytes32[] calldata clientIds,
        uint8[] calldata states
    ) external onlyCoordinator {
        Round storage r = rounds[roundId];
        if (r.phase != Phase.SUBMIT) revert InvalidState();
        if (clientIds.length == 0 || clientIds.length != states.length) revert InvalidArgument();
        for (uint256 i = 0; i < clientIds.length; ++i) {
            bytes32 clientId = clientIds[i];
            uint8 state = states[i];
            if (submissionHash[roundId][clientId] == bytes32(0)) revert MissingSubmission();
            if (decisionState[roundId][clientId] != 0) revert DuplicateDecision();
            if (state < 1 || state > 3) revert InvalidArgument();
            decisionState[roundId][clientId] = state;
            unchecked { r.decisionCount += 1; }
            emit DecisionPublished(roundId, clientId, state);
        }
    }

    function publishInitialState(
        uint256 roundId,
        bytes32 submissionRoot,
        bytes32 admittedRoot,
        bytes32 aggregateInputRoot,
        bytes32 checkpointHash
    ) external onlyCoordinator {
        Round storage r = rounds[roundId];
        if (r.phase != Phase.SUBMIT) revert InvalidState();
        if (r.submissionCount != r.expectedSubmissions || r.decisionCount != r.expectedSubmissions) {
            revert InvalidState();
        }
        _install(r, submissionRoot, admittedRoot, aggregateInputRoot, checkpointHash);
        r.phase = Phase.CHALLENGE;
        r.challengeEndBlock = uint64(block.number + r.challengeBlocks);
        emit StatePublished(roundId, checkpointHash, r.challengeEndBlock);
    }

    function openChallenge(
        uint256 roundId,
        DecisionKind kind,
        bytes32 clientId,
        uint8 claimedState,
        bytes32 evidenceHash
    ) external returns (uint256 challengeId) {
        Round storage r = rounds[roundId];
        if (r.phase != Phase.CHALLENGE) revert InvalidState();
        if (block.number > r.challengeEndBlock) revert ChallengeWindowClosed();
        if (kind != DecisionKind.AGGREGATE && submissionHash[roundId][clientId] == bytes32(0)) {
            revert MissingSubmission();
        }
        challengeId = nextChallengeId++;
        challenges[challengeId] = Challenge({
            roundId: roundId,
            kind: kind,
            clientId: clientId,
            claimedState: claimedState,
            evidenceHash: evidenceHash,
            certificateHash: bytes32(0),
            responseDeadline: uint64(block.number + r.responseBlocks),
            outcome: ChallengeOutcome.OPEN
        });
        unchecked { r.openChallenges += 1; }
        emit ChallengeOpened(challengeId, roundId, kind, clientId);
    }

    function resolveChallenge(
        uint256 challengeId,
        ChallengeOutcome outcome,
        uint8 correctedState,
        bytes32 certificateHash
    ) external onlyResolver {
        Challenge storage c = challenges[challengeId];
        if (c.outcome != ChallengeOutcome.OPEN) revert InvalidState();
        if (outcome == ChallengeOutcome.OPEN || certificateHash == bytes32(0)) revert InvalidArgument();
        if (block.number > c.responseDeadline) revert ResponseDeadlineExpired();
        Round storage r = rounds[c.roundId];
        if (r.phase != Phase.CHALLENGE && r.phase != Phase.RESOLVING) revert InvalidState();
        c.outcome = outcome;
        c.certificateHash = certificateHash;
        unchecked { r.openChallenges -= 1; }
        if (outcome == ChallengeOutcome.REVISED) {
            if (c.kind != DecisionKind.AGGREGATE) {
                if (correctedState < 1 || correctedState > 3) revert InvalidArgument();
                decisionState[c.roundId][c.clientId] = correctedState;
                emit DecisionPublished(c.roundId, c.clientId, correctedState);
            }
            r.needsReplacement = true;
            r.statePublished = false;
            r.phase = Phase.RESOLVING;
        }
        emit ChallengeResolved(challengeId, outcome, certificateHash);
    }

    /// @notice Publish a single terminal replacement.
    /// @dev No subsequent challenge is permitted. A malicious replacement can
    ///      therefore be laundered into finality; this is the intended ablation.
    function publishTerminalReplacement(
        uint256 roundId,
        bytes32 submissionRoot,
        bytes32 admittedRoot,
        bytes32 aggregateInputRoot,
        bytes32 checkpointHash
    ) external onlyCoordinator {
        Round storage r = rounds[roundId];
        if (r.phase != Phase.RESOLVING || !r.needsReplacement) revert InvalidState();
        if (r.openChallenges != 0) revert OpenChallengesRemain();
        _install(r, submissionRoot, admittedRoot, aggregateInputRoot, checkpointHash);
        r.needsReplacement = false;
        r.phase = Phase.READY;
        emit TerminalReplacementPublished(roundId, checkpointHash);
    }

    function finalize(uint256 roundId) external {
        Round storage r = rounds[roundId];
        if (r.phase == Phase.CHALLENGE) {
            if (block.number <= r.challengeEndBlock) revert ChallengeWindowOpen();
            if (r.openChallenges != 0 || !r.statePublished) revert InvalidState();
        } else if (r.phase == Phase.READY) {
            if (!r.statePublished || r.needsReplacement) revert InvalidState();
        } else {
            revert InvalidState();
        }
        r.phase = Phase.FINALIZED;
        emit RoundFinalized(roundId, r.checkpointHash);
    }

    function getRoundStatus(uint256 roundId) external view returns (
        Phase phase,
        uint32 openChallenges,
        uint64 challengeEndBlock,
        bool statePublished,
        bool needsReplacement,
        bytes32 checkpointHash
    ) {
        Round storage r = rounds[roundId];
        return (
            r.phase,
            r.openChallenges,
            r.challengeEndBlock,
            r.statePublished,
            r.needsReplacement,
            r.checkpointHash
        );
    }

    function _install(
        Round storage r,
        bytes32 submissionRoot,
        bytes32 admittedRoot,
        bytes32 aggregateInputRoot,
        bytes32 checkpointHash
    ) private {
        if (
            submissionRoot == bytes32(0) || admittedRoot == bytes32(0)
                || aggregateInputRoot == bytes32(0) || checkpointHash == bytes32(0)
        ) revert InvalidArgument();
        r.submissionRoot = submissionRoot;
        r.admittedRoot = admittedRoot;
        r.aggregateInputRoot = aggregateInputRoot;
        r.checkpointHash = checkpointHash;
        r.statePublished = true;
    }
}
