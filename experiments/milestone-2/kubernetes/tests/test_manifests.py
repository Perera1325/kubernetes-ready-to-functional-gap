"""Static checks of the deployment package (no cluster needed): YAML parses, probes match the config, images/args consistent,
Dockerfile COPY sources exist, no registry pulls at runtime. These are NOT evidence that the manifests work on a cluster."""
import glob, json, os, re, unittest
import yaml
K = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = json.load(open(os.path.join(K, "configs", "k8s-baseline.json")))


def docs(p): return [d for d in yaml.safe_load_all(open(os.path.join(K, p))) if d]


class T(unittest.TestCase):
    def test_all_yaml_parses(self):
        for f in glob.glob(os.path.join(K, "manifests", "*.yaml")) + [os.path.join(K, "configs", "kind-cluster.yaml")]:
            self.assertTrue(list(yaml.safe_load_all(open(f))), f)

    def test_kind_topology(self):
        c = docs("configs/kind-cluster.yaml")[0]; roles = [n["role"] for n in c["nodes"]]
        self.assertEqual(roles, ["control-plane", "worker", "worker"])
        for n in c["nodes"]: self.assertRegex(n["image"], r"^kindest/node:v\d+\.\d+\.\d+$")

    def test_probes_match_config_and_arms(self):
        deps = {d["metadata"]["name"]: d for d in docs("manifests/20-app.yaml") if d["kind"] == "Deployment"}
        self.assertEqual(set(deps), set(CFG["k8s"]["deployments"].values()))
        pr = CFG["probe"]
        for name, path in (("rfg-app-shallow", "/healthz/shallow"), ("rfg-app-deep", "/healthz/deep")):
            c = deps[name]["spec"]["template"]["spec"]["containers"][0]; rp = c["readinessProbe"]
            self.assertEqual(rp["httpGet"]["path"], path); self.assertEqual(rp["httpGet"]["port"], CFG["k8s"]["health_port"])
            self.assertEqual((rp["periodSeconds"], rp["timeoutSeconds"], rp["failureThreshold"], rp["successThreshold"], rp["initialDelaySeconds"]),
                             (pr["period_s"], pr["timeout_s"], pr["failure_threshold"], pr["success_threshold"], pr["initial_delay_s"]))
            self.assertNotIn("livenessProbe", c); self.assertEqual(deps[name]["spec"]["replicas"], 0)
            self.assertEqual(c["imagePullPolicy"], "Never"); a = c["args"]
            self.assertEqual(a[a.index("--dep-host") + 1], CFG["k8s"]["store_host"]); self.assertEqual(a[a.index("--cache-keys") + 1], str(CFG["cache_keys"]))
            self.assertEqual(a[a.index("--backoff-base") + 1], str(CFG["app"]["backoff_base_s"])); self.assertEqual(a[a.index("--backoff-cap") + 1], str(CFG["app"]["backoff_cap_s"]))

    def test_store_and_services(self):
        d = docs("manifests/10-store.yaml"); ss = next(x for x in d if x["kind"] == "StatefulSet")
        a = ss["spec"]["template"]["spec"]["containers"][0]["args"]
        self.assertEqual(a[a.index("--make-wal-if-missing") + 1:a.index("--make-wal-if-missing") + 3], [str(CFG["store"]["items"]), str(CFG["store"]["fill"])])
        self.assertTrue(ss["spec"]["volumeClaimTemplates"]); self.assertIn("tcpSocket", ss["spec"]["template"]["spec"]["containers"][0]["readinessProbe"])
        names = {x["metadata"]["name"] for x in d if x["kind"] == "Service"}; self.assertEqual(names, {"rfg-store", "rfg-store-hl"})
        self.assertEqual(ss["metadata"]["name"] + "-0", CFG["k8s"]["store_pod"])

    def test_rbac_covers_what_collector_does(self):
        r = next(x for x in docs("manifests/30-rbac.yaml") if x["kind"] == "Role")["rules"]
        flat = {(g, res, v) for rule in r for g in rule["apiGroups"] for res in rule["resources"] for v in rule["verbs"]}
        for need in (("", "pods", "delete"), ("", "pods", "watch"), ("discovery.k8s.io", "endpointslices", "watch"), ("apps", "deployments/scale", "patch")):
            self.assertIn(need, flat)

    def test_dockerfile_copy_sources_exist_and_bases_pinned(self):
        for f in glob.glob(os.path.join(K, "Dockerfiles", "*.Dockerfile")):
            t = open(f).read(); self.assertRegex(t, r"python:\d+\.\d+\.\d+-slim-bookworm")
            for m in re.finditer(r"^COPY (.+?) (\S+)$", t, re.M):
                for src in m.group(1).split(): self.assertTrue(os.path.exists(os.path.join(K, "src", src)), (f, src))

    def test_no_public_pull_at_runtime(self):
        for f in glob.glob(os.path.join(K, "manifests", "*")):
            for line in open(f):
                if "imagePullPolicy" in line: self.assertIn("Never", line)


if __name__ == "__main__":
    unittest.main()
