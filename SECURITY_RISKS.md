# Security Risk Assessment & Mitigation Strategies

## 🚨 Critical Identified Risk: Egress Control Bypass
**The Non-Possibility:**
*"You cannot prevent a harness from trying to make external API calls (like downloading a model or hitting an external tool) unless you also implement strict Kubernetes Network Policies (Egress filtering) that block the harness container from talking to anything except your LLM gateway and your sandbox environment."*

**Context:**
Even if we enforce execution inside a sandbox, the Harness Sidecar itself runs an open-source loop. If an LLM hallucinates or is subjected to prompt injection, the harness process inside the sidecar might attempt to `curl` external malicious domains, exfiltrate data, or bypass the LLM gateway by directly contacting an external LLM provider.

---

## 🛡️ Mitigation Strategies (To be evaluated and implemented)

To address this gap in the future, the platform engineering team must choose from one of the following architectural mitigations. All apply to any Kubernetes distribution (AKS, GKE, EKS, self-managed) — none of these options are cloud-specific.

### Option 1: Native Kubernetes Network Policies (Default Deny Egress)
Implement strict Layer 4 (IP/Port) Kubernetes Network Policies.
* **How it works:** Apply a `NetworkPolicy` to the developer's namespace that applies a `Default Deny` rule for all egress traffic from the Harness Sidecar.
* **Allowlist:** Explicitly allow egress *only* to the internal IP addresses/CIDRs of the LLM Gateway, the MCP Server, and the Sandbox Runtime. This is what the `k8s`/`aks` CLI generators already produce (see `cli/tethricor_cli/generators/k8s.py`).
* **Pros:** Native to Kubernetes, low overhead, highly secure.
* **Cons:** Hard to maintain if internal IPs change frequently; blocks benign external calls if the developer legitimately needed the agent to fetch a public library.

### Option 2: Istio / Service Mesh Egress Gateway
Force all traffic through an inspected Service Mesh proxy.
* **How it works:** Use Istio (or a similar mesh) to trap all outbound traffic from the sidecar. Route all external requests through a centralized Egress Gateway.
* **Pros:** Allows Layer 7 (HTTP/URL) filtering. You can block `api.openai.com` but allow `github.com`.
* **Cons:** Adds latency and complexity to the cluster architecture.

### Option 3: eBPF-based Enforcement (Cilium)
Use Cilium to monitor and enforce network security at the Linux kernel level.
* **How it works:** Cilium replaces `kube-proxy` and provides DNS-aware egress policies. You can specify exact domains (e.g., `allow: gateway.internal`) and completely drop all other packets natively in the kernel.
* **Pros:** High performance, DNS-aware (handles dynamic IPs), deep observability.
* **Cons:** Requires replacing or upgrading the cluster's CNI (Container Network Interface).

### Option 4: Transparent DNS Sinkholing (CoreDNS Customization)
* **How it works:** Configure the cluster's CoreDNS to intercept requests from the Harness sidecars. If a sidecar tries to resolve an external LLM or unauthorized API, the DNS server returns `NXDOMAIN` or a blackhole IP.
* **Pros:** Easy to implement centrally.
* **Cons:** Can be bypassed if the agent uses hardcoded IP addresses instead of DNS.

## Decision Matrix / Next Steps
1. Immediate term: Proceed with development, but do not deploy workloads with sensitive PII using these sidecars until Egress is locked down.
2. Short term: Implement **Option 1 (Kubernetes Network Policies)** as the baseline perimeter defense.
3. Long term: Evaluate **Option 2 or 3** for granular Layer 7 control.
