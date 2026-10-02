// Exercise Renovate without credentials; replacement writes use a temporary directory.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { execFileSync } = require("node:child_process");
const renovate = path.resolve(process.argv[2]);
const load = (name) => require(path.join(renovate, "dist", name));

const { extractPackageFile } = load("modules/manager/custom/regex/index.js");
const { doAutoReplace } = load(
  "workers/repository/update/branch/auto-replace.js",
);
const { GithubReleaseAttachmentsDatasource } = load(
  "modules/datasource/github-release-attachments/index.js",
);
const config = require(require.resolve("json5", { paths: [renovate] })).parse(
  fs.readFileSync("renovate.json5", "utf8"),
);

const expected = new Map([
  ["tests/conftest.py", ["mongo"]],
  ["benchmarks/stream_cost/topology.py", ["mongo"]],
  [
    ".github/workflows/test.yml",
    ["node", "prek", "ghcr.io/renovatebot/renovate", "uv"],
  ],
  [".github/workflows/publish.yml", ["uv"]],
  [".github/workflows/release-verification.yml", ["uv"]],
  [".github/workflows/stream-cost-benchmark.yml", ["uv"]],
  [".github/actions/setup-toolchain/action.yml", ["casey/just"]],
  [".python-version", ["python"]],
  ["Containerfile", ["prek", "tamasfe/taplo", "zizmor"]],
]);
const matchingManagers = (file) =>
  config.customManagers.filter((manager) =>
    manager.managerFilePatterns.some((pattern) =>
      new RegExp(pattern.slice(1, -1)).test(file),
    ),
  );
const extract = (file, content) =>
  matchingManagers(file).flatMap((manager) => {
    const extracted = extractPackageFile(content, file, manager);
    return (extracted?.deps ?? []).map((dependency, depIndex) => ({
      ...manager,
      ...extracted,
      ...dependency,
      manager: "regex",
      packageFile: file,
      depIndex,
      autoReplaceGlobalMatch: true,
    }));
  });

async function main() {
  await load("logger/index.js").init();
  load("config/global.js").GlobalConfig.set({
    localDir: fs.mkdtempSync(
      path.join(require("node:os").tmpdir(), "executable-pin-proof-"),
    ),
  });
  assert.deepEqual(config.enabledManagers, ["custom.regex"]);
  assert.equal(config.automerge, false);
  assert.equal(config.minimumReleaseAge, "7 days");
  const files = execFileSync(
    "git",
    ["-c", `safe.directory=${process.cwd()}`, "ls-files", "-z"],
    { encoding: "utf8" },
  )
    .split("\0")
    .filter(Boolean);
  const observed = new Map();
  for (const file of files) {
    // Excluded files are never opened, including potentially sensitive files.
    if (!matchingManagers(file).length) continue;
    const content = fs.readFileSync(file, "utf8");
    const dependencies = extract(file, content);
    observed.set(
      file,
      dependencies.map((dependency) => dependency.depName).sort(),
    );
    assert.ok(dependencies.every((dependency) => !dependency.skipReason));
    for (const dependency of dependencies) {
      const newValue =
        dependency.depName === "mongo"
          ? "8.0.5-noble"
          : dependency.depName === "python"
            ? "3.14.7"
            : dependency.depName === "node"
              ? "24"
              : "99.0.0";
      const newDigest =
        dependency.depName === "ghcr.io/renovatebot/renovate"
          ? "sha256:" + "a".repeat(64)
          : "a".repeat(64);
      const replaced = await doAutoReplace(
        { ...dependency, newValue, newDigest },
        content,
        false,
      );
      assert.ok(replaced, `Replacement failed: ${file}:${dependency.depName}`);
      const updated = extract(file, replaced).filter(
        (entry) => entry.depName === dependency.depName,
      );
      assert.ok(updated.every((entry) => entry.currentValue === newValue));
      if (dependency.depName === "ghcr.io/renovatebot/renovate") {
        assert.equal(updated[0].currentDigest, newDigest);
        assert.ok(replaced.includes(`renovate:${newValue}@${newDigest}`));
      }
      if (dependency.depName === "tamasfe/taplo") {
        assert.equal(updated[0].currentDigest, newDigest);
        assert.ok(
          replaced.includes(`/download/${newValue}/taplo-linux-x86_64.gz`),
        );
        assert.ok(
          replaced.includes(
            'test "$(taplo --version)" = "taplo ${TAPLO_TOOL_VERSION}"',
          ),
        );
      }
      if (
        file === ".github/workflows/test.yml" &&
        dependency.depName === "prek"
      ) {
        assert.ok(replaced.includes('uv tool install "prek==${PREK_VERSION}"'));
        assert.ok(replaced.includes("-v${{ env.PREK_VERSION }}-"));
      }
    }
  }
  assert.deepEqual(
    observed,
    new Map([...expected].map(([file, names]) => [file, names.sort()])),
  );
  const coupled = (name) =>
    [...expected.keys()]
      .flatMap((file) => extract(file, fs.readFileSync(file, "utf8")))
      .filter((dependency) => dependency.depName === name)
      .map((dependency) => dependency.currentValue);
  for (const name of ["mongo", "uv", "prek"])
    assert.equal(new Set(coupled(name)).size, 1, `${name} selections diverged`);
  for (const file of [
    "reports/stream-cost/example.py",
    "tests/test_fixture.py",
    "pyproject.toml",
    "package.json",
    "uv.lock",
    ".pre-commit-config.yaml",
    "docker-compose.yml",
  ]) {
    assert.equal(
      matchingManagers(file).length,
      0,
      `Unexpected ownership: ${file}`,
    );
  }
  const container = fs.readFileSync("Containerfile", "utf8");
  assert.ok(!container.includes("_PACKAGE_VERSION"));
  assert.ok(
    container.includes('PYTHON_TOOL_VERSION="$(cat /tmp/python-version)"'),
  );
  const action = fs.readFileSync(
    ".github/actions/setup-toolchain/action.yml",
    "utf8",
  );
  assert.ok(action.includes("cat .python-version"));
  assert.ok(
    action.includes("python-version: ${{ steps.python.outputs.version }}"),
  );
  for (const file of [...expected.keys()].filter((file) =>
    file.startsWith(".github/workflows/"),
  )) {
    const workflow = fs.readFileSync(file, "utf8");
    assert.ok(!workflow.includes("PYTHON_VERSION"));
    assert.ok(!workflow.includes("python-version:"));
    assert.ok(workflow.includes("uses: $/.github/actions/setup-toolchain"));
  }
  // Exercise stock digest mapping against deterministic release attachments.
  const datasource = new GithubReleaseAttachmentsDatasource();
  const digest = "b".repeat(64);
  const asset = {
    assetName: "taplo-linux-x86_64.gz",
    currentVersion: "0.10.0",
    currentDigest: "a".repeat(64),
  };
  datasource.downloadAndDigest = async () => digest;
  assert.equal(
    await datasource.mapDigestAssetToRelease(asset, {
      tag_name: "0.11.0",
      assets: [
        {
          name: asset.assetName,
          browser_download_url: "https://example.invalid/taplo.gz",
        },
      ],
    }),
    digest,
  );
  assert.equal(
    await datasource.mapDigestAssetToRelease(asset, {
      tag_name: "0.11.0",
      assets: [],
    }),
    null,
  );
  datasource.findDigestAsset = async () => null;
  datasource.http.getJsonUnchecked = async () => ({
    body: { tag_name: "0.10.0", assets: [] },
  });
  // Stock lookup retains an unrecognized digest; the image build must reject it.
  assert.equal(
    await datasource.getDigest(
      {
        packageName: "tamasfe/taplo",
        currentValue: "0.10.0",
        currentDigest: asset.currentDigest,
      },
      "0.11.0",
    ),
    asset.currentDigest,
  );
  assert.ok(container.includes("ADD --checksum=sha256:"));
  console.log(
    "14 executable occurrences extracted and replaced; ownership, coupling, consumers, and digest failure cases verified.",
  );
}
main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
