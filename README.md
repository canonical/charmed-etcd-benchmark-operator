<!--
Avoid using this README file for information that is maintained or published elsewhere, e.g.:

* charmcraft.yaml > published on Charmhub
* documentation > published on (or linked to from) Charmhub
* detailed contribution guide > documentation or CONTRIBUTING.md

Use links instead.
-->

# charmed-etcd-benchmark-operator

This is a machine charm for the [etcd benchmarking tool](https://github.com/etcd-io/etcd/tree/main/tools/benchmark).
It is meant to be deployed alongside charmed-etcd, in order to carry out performance benchmarking of the charmed etcd cluster.

## Usage and local testing

1. Navigate to the root of this project, and pack the charm.
```bash
charmcraft pack
```

2. Create a new model on a juju lxd cloud. We shall deploy our apps in this model. Let's begin by deploying the packed charm.
```bash
juju add-model etcd-benchmarking
```

3. Deploy the packed benchmarking charm. 
Then deploy [charmed-etcd](https://charmhub.io/charmed-etcd?channel=3.6/edge) from [Charmhub](https://charmhub.io/), with as many units as needed.
```bash
juju deploy ./charmed-etcd-benchmark-operator_ubuntu@24.04-amd64.charm

juju deploy charmed-etcd --channel 3.6/edge -n 2
```

4. As described in the [charmed-etcd docs](https://canonical-charmed-etcd.readthedocs-hosted.com/), we will need TLS certificates in order to integrate charmed-etcd with 
client applications (in our case, charmed-etcd-benchmarking-operator). Let's deploy the self-signed-certificate charm to help us with this.
```bash
juju deploy self-signed-certificates --channel edge
```

5. Status of the deployed apps can be checked like so.
```bash
juju status --watch 3s --integrations
```

5. Once all three deployed applications are active and all agents idle, 
integrate self-signed-certificates with charmed-etcd and charmed-etcd-benchmarkig-operator.
```bash
juju integrate charmed-etcd:client-certificates self-signed-certificates

juju integrate charmed-etcd-benchmark-operator self-signed-certificates
```

6. Once agents and apps have settled and integrations are available, the charmed-etcd-benchmarking-operator
can now be integrated with charmed-etcd. 
```bash
juju integrate charmed-etcd-benchmark-operator charmed-etcd
```

7. Wait for the apps and agents to settle, and for the integrations to be established.
Finally, the benchmarking action, `run`, can now be run.
```bash
juju run charmed-etcd-benchmark-operator/leader run
```

8. By default, the run action will initiate the benchmark, and it will continue to run indefinitely, 
until it is stopped with the `stop` action. 
```bash
juju run charmed-etcd-benchmark-operator/leader stop
```

9. Alternatively, there are two ways to bound the benchmark run: setting the `duration` (in seconds), or `total-transaction` configs. The test will terminate accordingly.
In case both are set, the test will terminate when either of the conditions is met.
```bash
juju config charmed-etcd-benchmark-operator duration=1200

juju config charmed-etcd-benchmark-operator total-transactions=100000
```

10. Another option of note is `report-interval`, which determines how often (in seconds) the benchmark results are reported. 
By default, it is set to 10 seconds.
```bash
juju config charmed-etcd-benchmark-operator report-interval=30
````

11. For a full list of config options, their implications and defaults, you can run the juju config command.
A few examples are `test-name`, `rate`, `rw-ratio`, etc. which allow for further customization of the benchmark tests. 

```bash
juju config charmed-etcd-benchmark-operator

juju config charmed-etcd-benchmark-operator test-name="my-etcd-benchmark" rate=200 rw-ratio=2
```

12. At any point in time, the tests—in progress or completed—can be viewed using the `list-tests` action. 
This action will list all test-ids of the tests that have been initiated, along with their status (in-progress or finished).
```bash
juju run charmed-etcd-benchmark-operator/leader list-tests
```

13. To view the summary of a test, the `get-summary` action can be used with the test-id as a param.
```bash
juju run charmed-etcd-benchmark-operator/leader get-summary --string-args test-id=<test-id>
```

14. Details are also logged to the juju log, and can be viewed using the following command:
```bash
juju debug-log --replay
```

### Integration with cos-lite bundle

This charm provides the `cos-agent` interface and exposes benchmark metrics in a Prometheus-friendly format,
thus enabling us to integrate with `grafana-agent` and the cos-lite bundle.
The steps below can be followed to view a grafana dashboard of the benchmark results:

1. Switch to a kubernetes controller, add a new model, and deploy the cos-lite bundle.
```bash
juju add-model cos

curl -L https://raw.githubusercontent.com/canonical/cos-lite-bundle/main/overlays/storage-small-overlay.yaml -O

juju deploy cos-lite \
        --trust \
        --overlay ./offers-overlay.yaml
```

2. Switch back to the lxd controller, and consume the offers from the cos-lite bundle.
```bash
juju switch <machine_model>

juju consume <k8s_controller>:admin/cos.prometheus-receive-remote-write
juju consume <k8s_controller>:admin/cos.grafana-dashboards
```

3. Deploy grafana-agent in the same model as charmed-etcd-benchmark-operator, and integrate the charms.
```bash
juju deploy grafana-agent --base ubuntu@24.04

juju integrate grafana-agent charmed-etcd-benchmark-operator
```

4. Finally, integrate grafana-agent with the cos bundle offers.
```bash
juju integrate grafana-agent prometheus-receive-remote-write
juju integrate grafana-agent grafana-dashboards
```

5. We can now view the benchmark metrics and dashboard in Grafana. The endpoint and password can be queried like so:
```bash
juju switch <k8s_model>

juju run traefik/0 show-proxied-endpoints --format=yaml \
  | yq '."traefik/0".results."proxied-endpoints"' \
  | jq

juju run grafana/leader get-admin-password --model cos
```

## Other resources

<!-- If your charm is documented somewhere else other than Charmhub, provide a link separately. -->

- [Read more](https://example.com)

- [Contributing](CONTRIBUTING.md) <!-- or link to other contribution documentation -->

- See the [Juju documentation](https://documentation.ubuntu.com/juju/3.6/howto/manage-charms/) for more information about developing and improving charms.
Benchmark stderr