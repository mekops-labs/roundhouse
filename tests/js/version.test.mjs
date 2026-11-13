import assert from "node:assert/strict";
import { test } from "node:test";

import { changelogUrl } from "../../custom_components/roundhouse/panel/version.js";

test("a release version links to the changelog at its tag", () => {
  assert.equal(
    changelogUrl("0.2.0"),
    "https://github.com/mekops-labs/roundhouse/blob/v0.2.0/CHANGELOG.md",
  );
  assert.equal(
    changelogUrl("12.34.567"),
    "https://github.com/mekops-labs/roundhouse/blob/v12.34.567/CHANGELOG.md",
  );
});

test("any other version is plain text", () => {
  for (const version of ["0.2.0-dev", "dev", "v0.2.0", "0.2", "0.2.0.1", "", null, undefined, 2]) {
    assert.equal(changelogUrl(version), null, String(version));
  }
});
