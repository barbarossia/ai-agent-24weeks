# Egress node health notes

## Healthy node selection

The active egress node must report `ready`. A `draining` node is not a valid route target. The node status and an edge event that names the same node state are independent evidence for a node-health diagnosis.

## Failover verification

For the synthetic lab, shifting the media route to `egress-us-b` is an allowlisted simulation only. Re-read both the node status and routing target after approval.
