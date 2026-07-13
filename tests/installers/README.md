# AI-PLC installer acceptance tests

The suite uses only Python 3's standard library and creates fixtures under `/private/tmp`.
It never installs into the caller's repository.

```bash
python3 tests/installers/run_acceptance.py --validate-matrix
python3 tests/installers/run_acceptance.py --batch 1
python3 tests/installers/run_acceptance.py --suite LCK --suite RACE
python3 tests/installers/run_acceptance.py --report tests/installers/results/latest.json
```

The machine-readable contract source is `case_matrix.json`. A full run requires:

- 13/13 mapped contract references and zero duplicate IDs;
- 183 cases, zero failures, errors, skips, or Not Tested cases;
- unchanged installer source hashes;
- zero temporary directories, worktrees, child processes, and transaction artifacts.

Fault-oriented tests import the filesystem helper directly or use an isolated distribution copy.
Production installer files are read-only during the run. A product failure remains a failing case and
must be returned to T003/T004; the validation task must not patch the installer implementation.
