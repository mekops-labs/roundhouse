// The running version in the page header, linked to its changelog entry.

const RELEASE = /^\d+\.\d+\.\d+$/;
const CHANGELOG = "https://github.com/mekops-labs/roundhouse/blob";

// The changelog at the tag of a release version, or null for any other string.
export function changelogUrl(version) {
  if (typeof version !== "string" || !RELEASE.test(version)) return null;
  return `${CHANGELOG}/v${version}/CHANGELOG.md`;
}
