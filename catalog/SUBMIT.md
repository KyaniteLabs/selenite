# Submitting Selenite to the Hermes plugin catalog

The maintainer's clicks only, on Nov 11 by 11:00 AM PT. Nothing upstream has been opened or posted.

## Before the PR can open

The repo is public and `main` is launched. The catalog pins `51e780482936e7211a829e26271795cf76c44f92`, and CI at that commit passed hermes-validate and tests 3.10 to 3.14 ([run](https://github.com/KyaniteLabs/selenite/actions/runs/42941467120)).

1. **Check the pin exists on GitHub:** `gh api repos/KyaniteLabs/selenite/commits/51e780482936e7211a829e26271795cf76c44f92 --jq .sha`
2. **Validate the pinned tree, not today's main:**
   ```sh
   mkdir -p ~/hackathon-submit/selenite && cd ~/hackathon-submit/selenite
   git clone https://github.com/KyaniteLabs/selenite.git product
   git -C product archive 51e780482936e7211a829e26271795cf76c44f92 | (mkdir pinned && tar -x -C pinned)
   hermes plugins validate pinned --json      # expect ok true, no warnings
   ```
3. Fill the last unchecked box in `catalog/PR-BODY.md` with the demo link.

## Opening it (the maintainer's personal GitHub login)

```sh
gh auth status                                   # your personal account, not the factory bot
gh repo fork NousResearch/hermes-agent --clone && cd hermes-agent
git switch -c catalog/selenite
cp ../product/catalog/selenite.yaml plugin-catalog/selenite.yaml
python -m pytest tests/hermes_cli/test_plugin_catalog.py -q
git add plugin-catalog/selenite.yaml && git commit -m "catalog: add Selenite"
git push -u origin catalog/selenite
gh pr create --repo NousResearch/hermes-agent --base main --title "catalog: add Selenite" --body-file ../product/catalog/PR-BODY.md
gh pr view --web
```

Then post the video on X tagging @NousResearch, and submit the Typeform: https://form.typeform.com/to/FwJLvOln
