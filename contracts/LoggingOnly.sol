// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @notice Blockchain logging baseline without challenge or correction semantics.
contract LoggingOnly {
    struct Round {
        uint32 expectedSubmissions;
        uint32 submissionCount;
        bool statePublished;
        bool finalized;
        bytes32 submissionRoot;
        bytes32 admittedRoot;
        bytes32 aggregateInputRoot;
        bytes32 checkpointHash;
    }

    address public immutable coordinator;
    mapping(uint256 => Round) public rounds;
    mapping(uint256 => mapping(bytes32 => bytes32)) public submissions;

    event RoundOpened(uint256 indexed roundId, uint32 expectedSubmissions);
    event SubmissionReceived(uint256 indexed roundId, bytes32 indexed clientId, bytes32 updateHash);
    event StatePublished(uint256 indexed roundId, bytes32 checkpointHash);
    event RoundFinalized(uint256 indexed roundId, bytes32 checkpointHash);

    error CoordinatorOnly();
    error InvalidState();
    error InvalidArgument();

    modifier onlyCoordinator() {
        if (msg.sender != coordinator) revert CoordinatorOnly();
        _;
    }

    constructor(address initialCoordinator) {
        if (initialCoordinator == address(0)) revert InvalidArgument();
        coordinator = initialCoordinator;
    }

    function openRound(uint256 roundId, uint32 expectedSubmissions) external onlyCoordinator {
        Round storage r = rounds[roundId];
        if (r.expectedSubmissions != 0 || expectedSubmissions == 0) revert InvalidState();
        r.expectedSubmissions = expectedSubmissions;
        emit RoundOpened(roundId, expectedSubmissions);
    }

    function submit(uint256 roundId, bytes32 clientId, bytes32 updateHash) external {
        Round storage r = rounds[roundId];
        if (r.expectedSubmissions == 0 || r.finalized || submissions[roundId][clientId] != bytes32(0)) revert InvalidState();
        submissions[roundId][clientId] = updateHash;
        unchecked { r.submissionCount += 1; }
        emit SubmissionReceived(roundId, clientId, updateHash);
    }

    function publishState(
        uint256 roundId,
        bytes32 submissionRoot,
        bytes32 admittedRoot,
        bytes32 aggregateInputRoot,
        bytes32 checkpointHash
    ) external onlyCoordinator {
        Round storage r = rounds[roundId];
        if (r.submissionCount != r.expectedSubmissions || r.statePublished) revert InvalidState();
        if (submissionRoot == bytes32(0) || admittedRoot == bytes32(0) || aggregateInputRoot == bytes32(0) || checkpointHash == bytes32(0)) revert InvalidArgument();
        r.submissionRoot = submissionRoot;
        r.admittedRoot = admittedRoot;
        r.aggregateInputRoot = aggregateInputRoot;
        r.checkpointHash = checkpointHash;
        r.statePublished = true;
        emit StatePublished(roundId, checkpointHash);
    }

    function finalize(uint256 roundId) external onlyCoordinator {
        Round storage r = rounds[roundId];
        if (!r.statePublished || r.finalized) revert InvalidState();
        r.finalized = true;
        emit RoundFinalized(roundId, r.checkpointHash);
    }
}
