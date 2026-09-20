// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @notice Representative eager-verification design point.
/// @dev The same off-chain evidence adapters used by ContestFL are executed for
///      every round. A resolver certificate installs the verified canonical
///      state before finalization. This is not a line-by-line reproduction of a
///      particular published zkFL system.
contract EagerVerification {
    enum Phase { NONE, SUBMIT, VERIFY, READY, FINALIZED, ABORTED }

    struct Round {
        uint32 expectedSubmissions;
        uint32 submissionCount;
        uint32 decisionCount;
        uint32 verificationBlocks;
        uint64 verificationDeadline;
        Phase phase;
        bool candidatePublished;
        bool verified;
        bytes32 submissionRoot;
        bytes32 admittedRoot;
        bytes32 aggregateInputRoot;
        bytes32 checkpointHash;
        bytes32 certificateHash;
        bytes32 evidenceRoot;
    }

    address public immutable coordinator;
    address public immutable resolver;

    mapping(uint256 => Round) public rounds;
    mapping(uint256 => mapping(bytes32 => bytes32)) public submissionHash;
    mapping(uint256 => mapping(bytes32 => uint8)) public decisionState;

    event RoundOpened(uint256 indexed roundId, uint32 expectedSubmissions, uint32 verificationBlocks);
    event SubmissionReceived(uint256 indexed roundId, bytes32 indexed clientId, bytes32 updateHash);
    event DecisionPublished(uint256 indexed roundId, bytes32 indexed clientId, uint8 state);
    event CandidatePublished(uint256 indexed roundId, bytes32 checkpointHash, uint64 verificationDeadline);
    event VerifiedStateInstalled(
        uint256 indexed roundId,
        bytes32 checkpointHash,
        bytes32 certificateHash,
        bytes32 evidenceRoot
    );
    event RoundFinalized(uint256 indexed roundId, bytes32 checkpointHash);
    event RoundAborted(uint256 indexed roundId, bytes32 reason);

    error CoordinatorOnly();
    error ResolverOnly();
    error InvalidState();
    error InvalidArgument();
    error MissingSubmission();
    error DuplicateSubmission();
    error DuplicateDecision();
    error VerificationDeadlineOpen();
    error VerificationDeadlineExpired();

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
        uint32 verificationBlocks
    ) external onlyCoordinator {
        Round storage r = rounds[roundId];
        if (r.phase != Phase.NONE) revert InvalidState();
        if (expectedSubmissions == 0 || verificationBlocks == 0) revert InvalidArgument();
        r.expectedSubmissions = expectedSubmissions;
        r.verificationBlocks = verificationBlocks;
        r.phase = Phase.SUBMIT;
        emit RoundOpened(roundId, expectedSubmissions, verificationBlocks);
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

    function publishCandidateState(
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
        _checkState(submissionRoot, admittedRoot, aggregateInputRoot, checkpointHash);
        r.submissionRoot = submissionRoot;
        r.admittedRoot = admittedRoot;
        r.aggregateInputRoot = aggregateInputRoot;
        r.checkpointHash = checkpointHash;
        r.candidatePublished = true;
        r.phase = Phase.VERIFY;
        r.verificationDeadline = uint64(block.number + r.verificationBlocks);
        emit CandidatePublished(roundId, checkpointHash, r.verificationDeadline);
    }

    /// @notice Install the state accepted by the eager evidence suite.
    /// @dev The resolver may overwrite a faulty candidate, but every round must
    ///      carry a non-zero certificate and evidence-root commitment.
    function installVerifiedState(
        uint256 roundId,
        bytes32 submissionRoot,
        bytes32 admittedRoot,
        bytes32 aggregateInputRoot,
        bytes32 checkpointHash,
        bytes32 certificateHash,
        bytes32 evidenceRoot
    ) external onlyResolver {
        Round storage r = rounds[roundId];
        if (r.phase != Phase.VERIFY || !r.candidatePublished) revert InvalidState();
        if (block.number > r.verificationDeadline) revert VerificationDeadlineExpired();
        if (certificateHash == bytes32(0) || evidenceRoot == bytes32(0)) revert InvalidArgument();
        _checkState(submissionRoot, admittedRoot, aggregateInputRoot, checkpointHash);
        r.submissionRoot = submissionRoot;
        r.admittedRoot = admittedRoot;
        r.aggregateInputRoot = aggregateInputRoot;
        r.checkpointHash = checkpointHash;
        r.certificateHash = certificateHash;
        r.evidenceRoot = evidenceRoot;
        r.verified = true;
        r.phase = Phase.READY;
        emit VerifiedStateInstalled(roundId, checkpointHash, certificateHash, evidenceRoot);
    }

    function expireVerification(uint256 roundId) external {
        Round storage r = rounds[roundId];
        if (r.phase != Phase.VERIFY) revert InvalidState();
        if (block.number <= r.verificationDeadline) revert VerificationDeadlineOpen();
        r.phase = Phase.ABORTED;
        emit RoundAborted(roundId, sha256(abi.encodePacked("ContestFL:eager-verifier-timeout", roundId)));
    }

    function finalize(uint256 roundId) external {
        Round storage r = rounds[roundId];
        if (r.phase != Phase.READY || !r.verified) revert InvalidState();
        r.phase = Phase.FINALIZED;
        emit RoundFinalized(roundId, r.checkpointHash);
    }

    function getRoundStatus(uint256 roundId) external view returns (
        Phase phase,
        bool candidatePublished,
        bool verified,
        uint64 verificationDeadline,
        bytes32 checkpointHash,
        bytes32 certificateHash,
        bytes32 evidenceRoot
    ) {
        Round storage r = rounds[roundId];
        return (
            r.phase,
            r.candidatePublished,
            r.verified,
            r.verificationDeadline,
            r.checkpointHash,
            r.certificateHash,
            r.evidenceRoot
        );
    }

    function _checkState(
        bytes32 submissionRoot,
        bytes32 admittedRoot,
        bytes32 aggregateInputRoot,
        bytes32 checkpointHash
    ) private pure {
        if (
            submissionRoot == bytes32(0) || admittedRoot == bytes32(0)
                || aggregateInputRoot == bytes32(0) || checkpointHash == bytes32(0)
        ) revert InvalidArgument();
    }
}
