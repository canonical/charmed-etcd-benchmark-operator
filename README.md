<!--
Avoid using this README file for information that is maintained or published elsewhere, e.g.:

* charmcraft.yaml > published on Charmhub
* documentation > published on (or linked to from) Charmhub
* detailed contribution guide > documentation or CONTRIBUTING.md

Use links instead.
-->

# charmed-etcd-benchmark-operator

This is a machine charm for the [etcd benchmarking tool](https://github.com/etcd-io/etcd/tree/main/tools/benchmark).
<!-- This charm will also include another benchmarking tool (etcdctl `check-perf`) soon -->
It is meant to be deployed alongside charmed-etcd, in order to carry out performance benchmarking of the charmed etcd cluster.

## Usage

1. Navigate to the root of this project, and pack the charm.
```commandline
charmcraft pack
```

2. Create a new model on a juju lxd cloud. We shall deploy our apps in this model. Let's begin by deploying the packed charm.
```commandline
juju add-model etcd-benchmarking

juju deploy ./charmed-etcd-benchmark-operator_ubuntu@24.04-amd64.charm
```

3. Deploy [charmed-etcd](https://charmhub.io/charmed-etcd?channel=3.6/edge) from [Charmhub](https://charmhub.io/), with as many units as needed.
```commandline
juju deploy charmed-etcd --channel 3.6/edge -n 2
```

4. As described in the [charmed-etcd docs](https://canonical-charmed-etcd.readthedocs-hosted.com/), we will need TLS certificates in order to integrate charmed-etcd with 
client applications (in our case, charmed-etcd-benchmarking-operator). Let's deploy the self-signed-certificate charm to help us with this.
```commandline
juju deploy self-signed-certificates --channel edge
```

5. Status of the deployed apps can we checked like so.
```commandline
juju status --watch 3s --integrations
```

5. Once all three deployed applications are active and all agents idle, 
integrate self-signed-certificates with charmed-etcd and charmed-etcd-benchmarkig-operator.
```commandline
juju integrate charmed-etcd:client-certificates self-signed-certificates

juju integrate charmed-etcd-benchmark-operator self-signed-certificates
```

6. Once agents and apps have settled and integrations are available, the charmed-etcd-benchmarking-operator
can now be integrated with charmed-etcd. 
```commandline
juju integrate charmed-etcd-benchmark-operator charmed-etcd
```

7. Wait for the apps and agents to settle, and for the integrations to be established.
Finally, the benchmarking action, `run`, can now be run. 
Ensure you wait 2-3 minutes for the task to complete, as the benchmarking exercise performs about 10000 transactions by default.
```commandline
juju run charmed-etcd-benchmark-operator/leader run --wait 3m
```

8. Performance metrics should be logged as a result of the action, on the CLI, for now. Here is an example:
```commandline
$ juju run charmed-etcd-benchmark-operator/leader run --wait 3m
Running operation 1 with 1 task
  - task 2 on unit-charmed-etcd-benchmark-operator-0

Waiting for task 2...
results: "bench with linearizable range\nTotal Read Ops: 5033\nDetails:\nSummary:\n
  \ Total:\t22.1473 secs.\n  Slowest:\t0.0129 secs.\n  Fastest:\t0.0006 secs.\n  Average:\t0.0015
  secs.\n  Stddev:\t0.0011 secs.\n  Requests/sec:\t227.2507\n\nResponse time histogram:\n
  \ 0.0006 [1]\t|\n  0.0019 [4011]\t|∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎\n  0.0031
  [616]\t|∎∎∎∎∎∎\n  0.0043 [218]\t|∎∎\n  0.0055 [103]\t|∎\n  0.0067 [45]\t|\n  0.0080                           
  [25]\t|\n  0.0092 [10]\t|\n  0.0104 [0]\t|\n  0.0116 [2]\t|\n  0.0129 [2]\t|\n\nLatency                       
  distribution:\n  10% in 0.0008 secs.\n  25% in 0.0009 secs.\n  50% in 0.0011 secs.\n                          
  \ 75% in 0.0016 secs.\n  90% in 0.0028 secs.\n  95% in 0.0038 secs.\n  99% in 0.0064                          
  secs.\n  99.9% in 0.0092 secs.\n\nTotal Write Ops: 4967\nDetails:\nSummary:\n  Total:\t22.1475                
  secs.\n  Slowest:\t0.0192 secs.\n  Fastest:\t0.0013 secs.\n  Average:\t0.0029 secs.\n                         
  \ Stddev:\t0.0013 secs.\n  Requests/sec:\t224.2694\n\nResponse time histogram:\n                              
  \ 0.0013 [1]\t|\n  0.0031 [3648]\t|∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎\n  0.0049                         
  [955]\t|∎∎∎∎∎∎∎∎∎∎\n  0.0067 [261]\t|∎∎\n  0.0085 [69]\t|\n  0.0102 [18]\t|\n  0.0120                         
  [9]\t|\n  0.0138 [2]\t|\n  0.0156 [2]\t|\n  0.0174 [0]\t|\n  0.0192 [2]\t|\n\nLatency                         
  distribution:\n  10% in 0.0019 secs.\n  25% in 0.0021 secs.\n  50% in 0.0024 secs.\n                          
  \ 75% in 0.0032 secs.\n  90% in 0.0044 secs.\n  95% in 0.0054 secs.\n  99% in 0.0076                          
  secs.\n  99.9% in 0.0141 secs."
```

9. Details are also logged to the juju log, and can be viewed using the following command:
```commandline
juju debug-log --replay
```

## Other resources

<!-- If your charm is documented somewhere else other than Charmhub, provide a link separately. -->

- [Read more](https://example.com)

- [Contributing](CONTRIBUTING.md) <!-- or link to other contribution documentation -->

- See the [Juju documentation](https://documentation.ubuntu.com/juju/3.6/howto/manage-charms/) for more information about developing and improving charms.
