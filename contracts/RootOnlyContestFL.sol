// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @notice Root-only ablation of the ContestFL state machine.
/// @dev Per-client submissions and decisions remain off chain. The ledger stores
///      only authenticated roots and reveals one sparse-Merkle path when a
///      decision is challenged. Resolver certificates remain the semantic trust
///      boundary, exactly as in the materialized prototype.
contract RootOnlyContestFL {
    enum Phase { NONE, CHALLENGE, READY, FINALIZED, ABORTED }
    enum Outcome { OPEN, REVISED, UPHELD, DISMISSED }

    struct Round {
        uint32 expectedClients;
        uint32 challengeBlocks;
        uint32 responseBlocks;
        uint32 epoch;
        uint32 openChallenges;
        uint8 retryBudget;
        uint8 retriesUsed;
        uint64 challengeEndBlock;
        Phase phase;
        bytes32 submissionRoot;
        bytes32 decisionRoot;
        bytes32 aggregateInputRoot;
        bytes32 checkpointHash;
    }

    struct Challenge {
        uint256 roundId;
        uint32 epoch;
        bytes32 clientId;
        uint8 observedState;
        address challenger;
        bytes32 reason;
        bytes32 evidenceHash;
        bytes32 certificateHash;
        uint64 openedBlock;
        uint64 responseDeadline;
        Outcome outcome;
    }

    address public immutable admin;
    address public coordinator;
    address public resolver;
    uint256 public nextChallengeId = 1;

    mapping(uint256 => Round) public rounds;
    mapping(uint256 => Challenge) public challenges;
    mapping(uint256 => bool) public aggregateChallenge;
    mapping(bytes32 => bool) public duplicateChallenge;

    event RolesChanged(address indexed coordinator, address indexed resolver);
    event RoundOpened(uint256 indexed roundId, uint32 expectedClients, uint8 retryBudget);
    event StatePublished(
        uint256 indexed roundId,
        uint32 indexed epoch,
        bytes32 submissionRoot,
        bytes32 decisionRoot,
        bytes32 aggregateInputRoot,
        bytes32 checkpointHash,
        uint64 challengeEndBlock
    );
    event ChallengeOpened(
        uint256 indexed challengeId,
        uint256 indexed roundId,
        uint32 indexed epoch,
        bytes32 clientId,
        uint8 observedState,
        address challenger
    );
    event ChallengeResolved(
        uint256 indexed challengeId,
        Outcome outcome,
        bytes32 certificateHash
    );
    event RoundFinalized(uint256 indexed roundId, bytes32 checkpointHash, uint32 epoch);
    event RoundAborted(uint256 indexed roundId, bytes32 reason);

    error AdminOnly();
    error CoordinatorOnly();
    error ResolverOnly();
    error InvalidPhase();
    error InvalidArgument();
    error ChallengeWindowOpen();
    error ChallengeWindowClosed();
    error InvalidChallenge();
    error InvalidProof();
    error RetryExhausted();
    error ResponseDeadlineExpired();
    error OpenChallengesRemain();

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
        if (initialCoordinator == address(0) || initialResolver == address(0)) {
            revert InvalidArgument();
        }
        admin = msg.sender;
        coordinator = initialCoordinator;
        resolver = initialResolver;
        emit RolesChanged(initialCoordinator, initialResolver);
    }

    function setRoles(address nextCoordinator, address nextResolver) external onlyAdmin {
        if (nextCoordinator == address(0) || nextResolver == address(0)) {
            revert InvalidArgument();
        }
        coordinator = nextCoordinator;
        resolver = nextResolver;
        emit RolesChanged(nextCoordinator, nextResolver);
    }

    function openRound(
        uint256 roundId,
        uint32 expectedClients,
        uint32 challengeBlocks,
        uint32 responseBlocks,
        uint8 retryBudget
    ) external onlyCoordinator {
        Round storage r = rounds[roundId];
        if (r.phase != Phase.NONE) revert InvalidPhase();
        if (expectedClients == 0 || challengeBlocks == 0 || responseBlocks == 0) {
            revert InvalidArgument();
        }
        r.expectedClients = expectedClients;
        r.challengeBlocks = challengeBlocks;
        r.responseBlocks = responseBlocks;
        r.retryBudget = retryBudget;
        r.phase = Phase.READY;
        emit RoundOpened(roundId, expectedClients, retryBudget);
    }

    function publishInitialState(
        uint256 roundId,
        bytes32 submissionRoot,
        bytes32 decisionRoot,
        bytes32 aggregateInputRoot,
        bytes32 checkpointHash
    ) external onlyCoordinator {
        Round storage r = rounds[roundId];
        if (r.phase != Phase.READY || r.epoch != 0) revert InvalidPhase();
        _requireRoots(submissionRoot, decisionRoot, aggregateInputRoot, checkpointHash);
        r.epoch = 1;
        r.submissionRoot = submissionRoot;
        r.decisionRoot = decisionRoot;
        r.aggregateInputRoot = aggregateInputRoot;
        r.checkpointHash = checkpointHash;
        r.phase = Phase.CHALLENGE;
        r.challengeEndBlock = uint64(block.number + r.challengeBlocks);
        emit StatePublished(
            roundId,
            r.epoch,
            submissionRoot,
            decisionRoot,
            aggregateInputRoot,
            checkpointHash,
            r.challengeEndBlock
        );
    }

    /// @notice Open a client-decision dispute by revealing only the challenged
    ///         leaf and its sparse-Merkle authentication path. The proof is
    ///         verified inside this state-changing transaction, so receipt gas
    ///         includes all SHA-256 path reconstruction performed below.
    function openDecisionChallenge(
        uint256 roundId,
        bytes32 clientId,
        uint8 observedState,
        bytes32[] calldata siblings,
        bytes32 reason,
        bytes32 evidenceHash
    ) external returns (uint256 challengeId) {
        Round storage r = rounds[roundId];
        if (r.phase != Phase.CHALLENGE) revert InvalidPhase();
        if (block.number > r.challengeEndBlock) revert ChallengeWindowClosed();
        if (clientId == bytes32(0) || observedState < 1 || observedState > 3) {
            revert InvalidArgument();
        }
        if (!verifySparseProof(clientId, abi.encodePacked(observedState), siblings, r.decisionRoot)) {
            revert InvalidProof();
        }
        bytes32 dedupe = keccak256(abi.encode(roundId, r.epoch, clientId, reason));
        if (duplicateChallenge[dedupe]) revert InvalidChallenge();
        duplicateChallenge[dedupe] = true;

        challengeId = nextChallengeId++;
        challenges[challengeId] = Challenge({
            roundId: roundId,
            epoch: r.epoch,
            clientId: clientId,
            observedState: observedState,
            challenger: msg.sender,
            reason: reason,
            evidenceHash: evidenceHash,
            certificateHash: bytes32(0),
            openedBlock: uint64(block.number),
            responseDeadline: uint64(block.number + r.responseBlocks),
            outcome: Outcome.OPEN
        });
        unchecked { r.openChallenges += 1; }
        emit ChallengeOpened(
            challengeId,
            roundId,
            r.epoch,
            clientId,
            observedState,
            msg.sender
        );
    }


    /// @notice Open an aggregate-checkpoint dispute. The aggregate-input root and
    ///         claimed checkpoint are already committed in the round state, so
    ///         this path requires no per-client materialization or Merkle witness.
    ///         The evidence hash binds the off-chain deterministic replay record.
    function openAggregateChallenge(
        uint256 roundId,
        bytes32 reason,
        bytes32 evidenceHash
    ) external returns (uint256 challengeId) {
        Round storage r = rounds[roundId];
        if (r.phase != Phase.CHALLENGE) revert InvalidPhase();
        if (block.number > r.challengeEndBlock) revert ChallengeWindowClosed();
        if (reason == bytes32(0) || evidenceHash == bytes32(0)) revert InvalidArgument();

        bytes32 dedupe = keccak256(abi.encode(roundId, r.epoch, bytes32(0), reason));
        if (duplicateChallenge[dedupe]) revert InvalidChallenge();
        duplicateChallenge[dedupe] = true;

        challengeId = nextChallengeId++;
        challenges[challengeId] = Challenge({
            roundId: roundId,
            epoch: r.epoch,
            clientId: bytes32(0),
            observedState: 0,
            challenger: msg.sender,
            reason: reason,
            evidenceHash: evidenceHash,
            certificateHash: bytes32(0),
            openedBlock: uint64(block.number),
            responseDeadline: uint64(block.number + r.responseBlocks),
            outcome: Outcome.OPEN
        });
        aggregateChallenge[challengeId] = true;
        unchecked { r.openChallenges += 1; }
        emit ChallengeOpened(
            challengeId,
            roundId,
            r.epoch,
            bytes32(0),
            0,
            msg.sender
        );
    }

    /// @notice Resolve a decision or aggregate challenge. A revision installs
    ///         the supplied successor roots/checkpoint and reopens scrutiny; an
    ///         upheld/dismissed challenge keeps the current state.
    function resolveDecisionChallenge(
        uint256 challengeId,
        Outcome outcome,
        bytes32 nextDecisionRoot,
        bytes32 nextAggregateInputRoot,
        bytes32 nextCheckpointHash,
        bytes32 certificateHash
    ) external onlyResolver {
        Challenge storage c = challenges[challengeId];
        if (c.outcome != Outcome.OPEN) revert InvalidChallenge();
        if (outcome != Outcome.REVISED && outcome != Outcome.UPHELD && outcome != Outcome.DISMISSED) {
            revert InvalidArgument();
        }
        if (certificateHash == bytes32(0)) revert InvalidArgument();
        if (block.number > c.responseDeadline) revert ResponseDeadlineExpired();

        Round storage r = rounds[c.roundId];
        if (r.phase != Phase.CHALLENGE || c.epoch != r.epoch) revert InvalidChallenge();
        c.outcome = outcome;
        c.certificateHash = certificateHash;
        unchecked { r.openChallenges -= 1; }

        if (outcome == Outcome.REVISED) {
            if (r.retriesUsed >= r.retryBudget) revert RetryExhausted();
            _requireRoots(r.submissionRoot, nextDecisionRoot, nextAggregateInputRoot, nextCheckpointHash);
            // An aggregate-checkpoint dispute may revise only the checkpoint;
            // client decisions and aggregate membership remain the committed inputs.
            if (
                aggregateChallenge[challengeId]
                    && (nextDecisionRoot != r.decisionRoot
                        || nextAggregateInputRoot != r.aggregateInputRoot)
            ) revert InvalidArgument();
            unchecked {
                r.retriesUsed += 1;
                r.epoch += 1;
            }
            r.decisionRoot = nextDecisionRoot;
            r.aggregateInputRoot = nextAggregateInputRoot;
            r.checkpointHash = nextCheckpointHash;
            r.challengeEndBlock = uint64(block.number + r.challengeBlocks);
            emit StatePublished(
                c.roundId,
                r.epoch,
                r.submissionRoot,
                r.decisionRoot,
                r.aggregateInputRoot,
                r.checkpointHash,
                r.challengeEndBlock
            );
        }
        emit ChallengeResolved(challengeId, outcome, certificateHash);
    }

    function finalize(uint256 roundId) external onlyCoordinator {
        Round storage r = rounds[roundId];
        if (r.phase != Phase.CHALLENGE) revert InvalidPhase();
        if (r.openChallenges != 0) revert OpenChallengesRemain();
        if (block.number <= r.challengeEndBlock) revert ChallengeWindowOpen();
        r.phase = Phase.FINALIZED;
        emit RoundFinalized(roundId, r.checkpointHash, r.epoch);
    }

    function abort(uint256 roundId, bytes32 reason) external onlyResolver {
        Round storage r = rounds[roundId];
        if (r.phase == Phase.FINALIZED || r.phase == Phase.ABORTED || r.phase == Phase.NONE) {
            revert InvalidPhase();
        }
        r.phase = Phase.ABORTED;
        emit RoundAborted(roundId, reason);
    }

    function verifySparseProof(
        bytes32 key,
        bytes memory value,
        bytes32[] memory siblings,
        bytes32 expectedRoot
    ) public pure returns (bool) {
        uint256 depth = siblings.length;
        if (depth < 8 || depth > 256) return false;
        uint256 index = uint256(key) >> (256 - depth);
        bytes32 node = sha256(abi.encodePacked("ContestFL:leaf", key, sha256(value)));
        for (uint256 height = 0; height < depth; ++height) {
            bytes32 sibling = siblings[height];
            node = (index & 1) == 1
                ? sha256(abi.encodePacked("ContestFL:node", sibling, node))
                : sha256(abi.encodePacked("ContestFL:node", node, sibling));
            index >>= 1;
        }
        return node == expectedRoot;
    }

    function _requireRoots(
        bytes32 submissionRoot,
        bytes32 decisionRoot,
        bytes32 aggregateInputRoot,
        bytes32 checkpointHash
    ) private pure {
        if (
            submissionRoot == bytes32(0)
                || decisionRoot == bytes32(0)
                || aggregateInputRoot == bytes32(0)
                || checkpointHash == bytes32(0)
        ) revert InvalidArgument();
    }
}
