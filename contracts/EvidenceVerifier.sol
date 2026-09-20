// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @notice Public verifier for the SHA-256 sparse-Merkle construction used by
///         the ContestFL evaluation harness.
contract EvidenceVerifier {
    function verifySparseProof(
        bytes32 key,
        bytes memory value,
        bool exists,
        bytes32[] memory siblings,
        bytes32 expectedRoot
    ) public pure returns (bool) {
        uint256 depth = siblings.length;
        require(depth >= 8 && depth <= 256, "invalid depth");
        uint256 index = uint256(key) >> (256 - depth);
        bytes32 node = exists
            ? sha256(abi.encodePacked("ContestFL:leaf", key, sha256(value)))
            : sha256(bytes("ContestFL:empty-leaf"));
        for (uint256 height = 0; height < depth; ++height) {
            bytes32 sibling = siblings[height];
            node = (index & 1) == 1
                ? sha256(abi.encodePacked("ContestFL:node", sibling, node))
                : sha256(abi.encodePacked("ContestFL:node", node, sibling));
            index >>= 1;
        }
        return node == expectedRoot;
    }

    function verifySparseProofOrRevert(
        bytes32 key,
        bytes calldata value,
        bool exists,
        bytes32[] calldata siblings,
        bytes32 expectedRoot
    ) external pure returns (bool) {
        require(verifySparseProof(key, value, exists, siblings, expectedRoot), "invalid sparse proof");
        return true;
    }
}
