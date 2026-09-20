// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @notice Experimental realization of the ContestFL dispute state machine.
/// @dev Model updates stay off-chain. The contract stores commitments, decision
///      lineages, canonical roots, challenges, retry accounting, and finality.
contract ContestFLExperiment {
    enum Phase { NONE, SUBMIT, CHALLENGE, RESOLVING, READY, FINALIZED, ABORTED }
    enum DecisionKind { ADMIT, INCLUDE, AGGREGATE }
    enum ChallengeOutcome { OPEN, UPHELD, REVISED, DISMISSED, MOOT }

    struct Round {
        uint32 expectedSubmissions;
        uint32 submissionCount;
        uint32 decisionCount;
        uint32 challengeBlocks;
        uint32 responseBlocks;
        uint32 epoch;
        uint32 openChallenges;
        uint8 retryBudget;
        uint8 retriesUsed;
        uint64 challengeEndBlock;
        Phase phase;
        bool statePublished;
        bool terminalCheckpoint;
        bool needsReplacement;
        bytes32 submissionRoot;
        bytes32 admittedRoot;
        bytes32 aggregateInputRoot;
        bytes32 checkpointHash;
    }

    struct Challenge {
        uint256 roundId;
        uint32 epoch;
        DecisionKind kind;
        bytes32 clientId;
        uint8 claimedState;
        address challenger;
        bytes32 reason;
        bytes32 evidenceHash;
        bytes32 certificateHash;
        uint64 openedBlock;
        uint64 responseDeadline;
        ChallengeOutcome outcome;
    }

    address public immutable admin;
    address public coordinator;
    address public resolver;
    uint256 public nextChallengeId = 1;

    mapping(uint256 => Round) public rounds;
    mapping(uint256 => mapping(bytes32 => bytes32)) public submissionHash;
    // 0 = absent, 1 = rejected, 2 = admitted but excluded, 3 = admitted and included.
    mapping(uint256 => mapping(bytes32 => uint8)) public decisionState;
    mapping(uint256 => mapping(bytes32 => uint32)) public decisionVersion;
    mapping(uint256 => Challenge) public challenges;
    mapping(bytes32 => bool) public duplicateChallenge;

    event RolesChanged(address indexed coordinator, address indexed resolver);
    event RoundOpened(uint256 indexed roundId, uint32 expectedSubmissions, uint8 retryBudget);
    event SubmissionReceived(uint256 indexed roundId, bytes32 indexed clientId, bytes32 updateHash);
    event DecisionPublished(uint256 indexed roundId, bytes32 indexed clientId, uint8 state, uint32 version);
    event StatePublished(
        uint256 indexed roundId,
        uint32 indexed epoch,
        bytes32 submissionRoot,
        bytes32 admittedRoot,
        bytes32 aggregateInputRoot,
        bytes32 checkpointHash,
        bool terminalCheckpoint,
        uint64 challengeEndBlock
    );
    event ChallengeOpened(
        uint256 indexed challengeId,
        uint256 indexed roundId,
        uint32 indexed epoch,
        DecisionKind kind,
        bytes32 clientId,
        address challenger
    );
    event ChallengeResolved(
        uint256 indexed challengeId,
        ChallengeOutcome outcome,
        uint8 correctedState,
        bytes32 certificateHash
    );
    event DescendantChallengeMoot(uint256 indexed challengeId);
    event ChallengeExpired(uint256 indexed challengeId, uint256 indexed roundId);
    event RoundFinalized(uint256 indexed roundId, bytes32 checkpointHash, uint32 epoch);
    event RoundAborted(uint256 indexed roundId, bytes32 reason);

    error AdminOnly();
    error CoordinatorOnly();
    error ResolverOnly();
    error InvalidPhase();
    error InvalidArgument();
    error DuplicateSubmission();
    error MissingSubmission();
    error DuplicateDecision();
    error ChallengeWindowClosed();
    error ChallengeWindowOpen();
    error InvalidChallenge();
    error RetryExhausted();
    error OpenChallengesRemain();
    error ResponseDeadlineOpen();
    error ResponseDeadlineExpired();

    modifier onlyAdmin() {
        if (msg.sender != admin) revert AdminOnly();
        _;
    }

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
        admin = msg.sender;
        coordinator = initialCoordinator;
        resolver = initialResolver;
        emit RolesChanged(initialCoordinator, initialResolver);
    }

    function setRoles(address nextCoordinator, address nextResolver) external onlyAdmin {
        if (nextCoordinator == address(0) || nextResolver == address(0)) revert InvalidArgument();
        coordinator = nextCoordinator;
        resolver = nextResolver;
        emit RolesChanged(nextCoordinator, nextResolver);
    }

    function openRound(
        uint256 roundId,
        uint32 expectedSubmissions,
        uint32 challengeBlocks,
        uint32 responseBlocks,
        uint8 retryBudget
    ) external onlyCoordinator {
        Round storage r = rounds[roundId];
        if (r.phase != Phase.NONE) revert InvalidPhase();
        if (expectedSubmissions == 0 || challengeBlocks == 0 || responseBlocks == 0) revert InvalidArgument();
        r.expectedSubmissions = expectedSubmissions;
        r.challengeBlocks = challengeBlocks;
        r.responseBlocks = responseBlocks;
        r.retryBudget = retryBudget;
        r.phase = Phase.SUBMIT;
        emit RoundOpened(roundId, expectedSubmissions, retryBudget);
    }

    function submit(uint256 roundId, bytes32 clientId, bytes32 updateHash) external {
        Round storage r = rounds[roundId];
        if (r.phase != Phase.SUBMIT) revert InvalidPhase();
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
        if (r.phase != Phase.SUBMIT) revert InvalidPhase();
        if (clientIds.length == 0 || clientIds.length != states.length) revert InvalidArgument();
        for (uint256 i = 0; i < clientIds.length; ++i) {
            bytes32 clientId = clientIds[i];
            uint8 state = states[i];
            if (submissionHash[roundId][clientId] == bytes32(0)) revert MissingSubmission();
            if (decisionState[roundId][clientId] != 0) revert DuplicateDecision();
            if (state < 1 || state > 3) revert InvalidArgument();
            decisionState[roundId][clientId] = state;
            decisionVersion[roundId][clientId] = 1;
            unchecked { r.decisionCount += 1; }
            emit DecisionPublished(roundId, clientId, state, 1);
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
        if (r.phase != Phase.SUBMIT) revert InvalidPhase();
        if (r.submissionCount != r.expectedSubmissions || r.decisionCount != r.expectedSubmissions) revert InvalidArgument();
        _installState(r, roundId, submissionRoot, admittedRoot, aggregateInputRoot, checkpointHash, false);
        r.phase = Phase.CHALLENGE;
        r.challengeEndBlock = uint64(block.number + r.challengeBlocks);
        emit StatePublished(roundId, r.epoch, submissionRoot, admittedRoot, aggregateInputRoot, checkpointHash, false, r.challengeEndBlock);
    }

    function openChallenge(
        uint256 roundId,
        DecisionKind kind,
        bytes32 clientId,
        uint8 claimedState,
        bytes32 reason,
        bytes32 evidenceHash
    ) external returns (uint256 challengeId) {
        Round storage r = rounds[roundId];
        if (r.phase != Phase.CHALLENGE) revert InvalidPhase();
        if (block.number > r.challengeEndBlock) revert ChallengeWindowClosed();
        if (kind != DecisionKind.AGGREGATE && submissionHash[roundId][clientId] == bytes32(0)) revert MissingSubmission();
        bytes32 dedupe = keccak256(abi.encode(roundId, r.epoch, kind, clientId, reason));
        if (duplicateChallenge[dedupe]) revert InvalidChallenge();
        duplicateChallenge[dedupe] = true;

        challengeId = nextChallengeId++;
        challenges[challengeId] = Challenge({
            roundId: roundId,
            epoch: r.epoch,
            kind: kind,
            clientId: clientId,
            claimedState: claimedState,
            challenger: msg.sender,
            reason: reason,
            evidenceHash: evidenceHash,
            certificateHash: bytes32(0),
            openedBlock: uint64(block.number),
            responseDeadline: uint64(block.number + r.responseBlocks),
            outcome: ChallengeOutcome.OPEN
        });
        unchecked { r.openChallenges += 1; }
        emit ChallengeOpened(challengeId, roundId, r.epoch, kind, clientId, msg.sender);
    }

    function resolveChallenge(
        uint256 challengeId,
        ChallengeOutcome outcome,
        uint8 correctedState,
        bytes32 certificateHash,
        uint256[] calldata mootChallengeIds
    ) external onlyResolver {
        Challenge storage c = challenges[challengeId];
        if (c.outcome != ChallengeOutcome.OPEN) revert InvalidChallenge();
        if (outcome != ChallengeOutcome.UPHELD && outcome != ChallengeOutcome.REVISED && outcome != ChallengeOutcome.DISMISSED) revert InvalidArgument();
        if (certificateHash == bytes32(0)) revert InvalidArgument();
        if (block.number > c.responseDeadline) revert ResponseDeadlineExpired();
        Round storage r = rounds[c.roundId];
        if (r.phase != Phase.CHALLENGE && r.phase != Phase.RESOLVING) revert InvalidPhase();

        c.outcome = outcome;
        c.certificateHash = certificateHash;
        unchecked { r.openChallenges -= 1; }

        if (outcome == ChallengeOutcome.REVISED) {
            if (c.kind != DecisionKind.AGGREGATE) {
                if (correctedState < 1 || correctedState > 3) revert InvalidArgument();
                decisionState[c.roundId][c.clientId] = correctedState;
                unchecked { decisionVersion[c.roundId][c.clientId] += 1; }
                emit DecisionPublished(c.roundId, c.clientId, correctedState, decisionVersion[c.roundId][c.clientId]);
            }
            r.statePublished = false;
            r.terminalCheckpoint = false;
            r.needsReplacement = true;
            r.phase = Phase.RESOLVING;
        }

        for (uint256 i = 0; i < mootChallengeIds.length; ++i) {
            Challenge storage descendant = challenges[mootChallengeIds[i]];
            if (descendant.roundId != c.roundId || descendant.epoch != c.epoch || descendant.outcome != ChallengeOutcome.OPEN) revert InvalidChallenge();
            descendant.outcome = ChallengeOutcome.MOOT;
            unchecked { r.openChallenges -= 1; }
            emit DescendantChallengeMoot(mootChallengeIds[i]);
        }

        emit ChallengeResolved(challengeId, outcome, correctedState, certificateHash);
    }

    /// @notice Conservatively abort a round when its configured single resolver
    ///         path has not answered before the response deadline. A production
    ///         resolver ladder can replace this transition with escalation.
    function expireChallenge(uint256 challengeId) external {
        Challenge storage c = challenges[challengeId];
        if (c.outcome != ChallengeOutcome.OPEN) revert InvalidChallenge();
        if (block.number <= c.responseDeadline) revert ResponseDeadlineOpen();
        Round storage r = rounds[c.roundId];
        c.outcome = ChallengeOutcome.DISMISSED;
        unchecked { r.openChallenges -= 1; }
        r.phase = Phase.ABORTED;
        emit ChallengeExpired(challengeId, c.roundId);
        emit RoundAborted(c.roundId, sha256(abi.encodePacked("ContestFL:resolver-timeout", challengeId)));
    }

    function publishCoordinatorReplacement(
        uint256 roundId,
        bytes32 submissionRoot,
        bytes32 admittedRoot,
        bytes32 aggregateInputRoot,
        bytes32 checkpointHash
    ) external onlyCoordinator {
        Round storage r = rounds[roundId];
        if (r.phase != Phase.RESOLVING || !r.needsReplacement) revert InvalidPhase();
        if (r.openChallenges != 0) revert OpenChallengesRemain();
        if (r.retriesUsed >= r.retryBudget) revert RetryExhausted();
        unchecked {
            r.retriesUsed += 1;
            r.epoch += 1;
        }
        _installState(r, roundId, submissionRoot, admittedRoot, aggregateInputRoot, checkpointHash, false);
        r.phase = Phase.CHALLENGE;
        r.challengeEndBlock = uint64(block.number + r.challengeBlocks);
        emit StatePublished(roundId, r.epoch, submissionRoot, admittedRoot, aggregateInputRoot, checkpointHash, false, r.challengeEndBlock);
    }

    function publishResolverFallback(
        uint256 roundId,
        bytes32 submissionRoot,
        bytes32 admittedRoot,
        bytes32 aggregateInputRoot,
        bytes32 checkpointHash
    ) external onlyResolver {
        Round storage r = rounds[roundId];
        if (r.phase != Phase.RESOLVING || !r.needsReplacement) revert InvalidPhase();
        if (r.openChallenges != 0) revert OpenChallengesRemain();
        unchecked { r.epoch += 1; }
        _installState(r, roundId, submissionRoot, admittedRoot, aggregateInputRoot, checkpointHash, true);
        r.phase = Phase.READY;
        emit StatePublished(roundId, r.epoch, submissionRoot, admittedRoot, aggregateInputRoot, checkpointHash, true, 0);
    }

    function finalize(uint256 roundId) external {
        Round storage r = rounds[roundId];
        if (r.phase == Phase.CHALLENGE) {
            if (block.number <= r.challengeEndBlock) revert ChallengeWindowOpen();
            if (r.openChallenges != 0 || !r.statePublished || r.needsReplacement) revert InvalidPhase();
        } else if (r.phase == Phase.READY) {
            if (!r.terminalCheckpoint || !r.statePublished || r.needsReplacement) revert InvalidPhase();
        } else {
            revert InvalidPhase();
        }
        r.phase = Phase.FINALIZED;
        emit RoundFinalized(roundId, r.checkpointHash, r.epoch);
    }

    function abortRound(uint256 roundId, bytes32 reason) external onlyResolver {
        Round storage r = rounds[roundId];
        if (r.phase == Phase.FINALIZED || r.phase == Phase.ABORTED || r.phase == Phase.NONE) revert InvalidPhase();
        r.phase = Phase.ABORTED;
        emit RoundAborted(roundId, reason);
    }

    function getRoundStatus(uint256 roundId) external view returns (
        Phase phase,
        uint32 epoch,
        uint8 retriesUsed,
        uint8 retryBudget,
        uint32 openChallenges,
        uint64 challengeEndBlock,
        bool statePublished,
        bool terminalCheckpoint,
        bool needsReplacement,
        bytes32 checkpointHash
    ) {
        Round storage r = rounds[roundId];
        return (
            r.phase,
            r.epoch,
            r.retriesUsed,
            r.retryBudget,
            r.openChallenges,
            r.challengeEndBlock,
            r.statePublished,
            r.terminalCheckpoint,
            r.needsReplacement,
            r.checkpointHash
        );
    }

    function _installState(
        Round storage r,
        uint256,
        bytes32 submissionRoot,
        bytes32 admittedRoot,
        bytes32 aggregateInputRoot,
        bytes32 checkpointHash,
        bool terminalCheckpoint
    ) internal {
        if (submissionRoot == bytes32(0) || admittedRoot == bytes32(0) || aggregateInputRoot == bytes32(0) || checkpointHash == bytes32(0)) revert InvalidArgument();
        r.submissionRoot = submissionRoot;
        r.admittedRoot = admittedRoot;
        r.aggregateInputRoot = aggregateInputRoot;
        r.checkpointHash = checkpointHash;
        r.statePublished = true;
        r.terminalCheckpoint = terminalCheckpoint;
        r.needsReplacement = false;
    }
}
