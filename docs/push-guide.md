# Publish the project to GitHub

The repository `namyikim/adaptive-llm-router` was created but is empty. If GitHub API application permissions are read-only, use GitHub CLI on your own machine instead.

**Security first:** revoke any personal access token disclosed in a chat, and use browser-based `gh auth login` rather than hard-coding credentials. This project needs **no tokens** for local Kev inference.

1. Extract `adaptive-llm-router-colab-a100.zip` to a folder named `adaptive-llm-router`.
2. In that folder, open a terminal and execute:

```bash
gh auth login -h github.com -p https -w
git init
git checkout -b main
git remote add origin https://github.com/namyikim/adaptive-llm-router.git
git add .
git commit -m "Add Kev A100 Colab routing lab"
git push -u origin main
```

The steps above assume the remote is empty. If it has been initialized in the meantime, first fetch the remote and reconcile its history instead of force-pushing.

After publishing, the `Open in Colab` badge in the README will work. You can also download `notebooks/kev_a100_colab.ipynb` directly and upload it to Colab **before publishing**: it includes a small self-contained fallback for demo modules and examples if the GitHub project is still empty. The official Kev source and model still require Colab internet access.

## Verify the project without a GPU

```bash
python -m unittest discover -s tests -v
```

Actual Kev-4B GPU inference and the official benchmark have not been executed in the authoring environment.
