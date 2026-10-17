# Local deterministic admission example

From the repository root, with the package installed or `PYTHONPATH=src`:

```sh
python -m mg8_runtime run examples/basic/unit.mg8 \
  --proposal examples/basic/proposal.json \
  --database local-run.sqlite --output local-run.qson
```

The proposal is a candidate state object, not an authority/evidence envelope.
The runtime checks `/candidate/answer != ""` using the predicate authored in
`gates.g8son`. The supplied string passes; an empty string fails; a missing or
wrong-typed answer is unresolved. No model, shell, network, or secret is needed
for the predicate. This checks nonemptiness, not the truth of the answer.

`unit.mg8` is canonical version 1.0. `flow.ork` deliberately declares the JSON
`mg8-runtime-sequential/0.1` profile; it is not a block ORK parser. `policy.bonit`
declares the JSON `mg8-runtime/0.1` profile. One version-1 GST resource contains
an explicit `state` object. All references resolve relative to the unit directory;
symlink resources are unsupported. Gate IDs must exactly match ORK flow order.

Loading is read-only. It freezes original source-byte SHA256 digests and detached
JSON snapshots. It neither opens the trace destination nor creates its parent.
The command above explicitly sends generated evidence outside the example sources.
