# Submitting Selenite to the Hermes plugin catalog

The maintainer's clicks only, on Nov 11 by 11:00 AM PT. Nothing here has been opened, pushed or posted.

## Before the PR can open

1. **Launch the GitHub repo.** The catalog installs from `https://github.com/KyaniteLabs/selenite` at the pinned SHA, and today that repo is an empty public teaser. Pushing `main` there is the launch, and it's your call. After you say "launch", the push is:
   `git -C <selenite checkout> push github main` (the push URL is fenced until then).
2. **Check the pin exists on GitHub:** `gh api repos/KyaniteLabs/selenite/commits/9caf3a7b071a2ee5d5bbbd392e9edb005f481928 --jq .sha`
3. **Validate the pinned tree, not today's main:**
   ```sh
   mkdir -p ~/hackathon-submit/selenite && cd ~/hackathon-submit/selenite
   git clone https://github.com/KyaniteLabs/selenite.git product
   git -C product archive 9caf3a7b071a2ee5d5bbbd392e9edb005f481928 | (mkdir pinned && tar -x -C pinned)
   hermes plugins validate pinned --json      # expect ok true, no warnings
   ```
4. Fill the three unchecked boxes in `catalog/PR-BODY.md` with the validate receipt, the CI run and the demo link. If a banner and screenshots exist at the pinned SHA, add `image:` and `screenshots:` to the yaml with raw URLs pinned to that SHA.

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
