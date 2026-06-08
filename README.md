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

10. Another option of note is `report-interval`, which determines how often (in seconds) the benchmark results are logged. 
By default, it is set to 10 seconds.
```bash
juju config charmed-etcd-benchmark-operator report-interval=30
```

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

## Other resources

<!-- If your charm is documented somewhere else other than Charmhub, provide a link separately. -->

- [Read more](https://example.com)

- [Contributing](CONTRIBUTING.md) <!-- or link to other contribution documentation -->

- See the [Juju documentation](https://documentation.ubuntu.com/juju/3.6/howto/manage-charms/) for more information about developing and improving charms.
