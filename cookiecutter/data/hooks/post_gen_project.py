import os
import shutil

# Handle R-specific files
r = '<< cookiecutter.r >>' == 'True'
if not r:
    os.remove(".lintr")
    os.remove(".Rprofile")
    os.remove("renv.lock")
    os.remove("vscode-packages.R")
    shutil.rmtree("renv", ignore_errors=True)

# Recreate symlinks in tex subdirectories
# Cookiecutter copies symlinks as regular files/dirs, so we need to fix them
tex_subdirs = ["tex/appendix", "tex/article", "tex/presentation"]

for subdir in tex_subdirs:
    if os.path.exists(subdir):
        assets_link = os.path.join(subdir, "assets")
        bib_link = os.path.join(subdir, "library.bib")
        
        # Remove the copied files/directories
        if os.path.exists(assets_link):
            if os.path.islink(assets_link):
                os.unlink(assets_link)
            elif os.path.isdir(assets_link):
                shutil.rmtree(assets_link)
            else:
                os.remove(assets_link)
        
        if os.path.exists(bib_link):
            if os.path.islink(bib_link):
                os.unlink(bib_link)
            else:
                os.remove(bib_link)
        
        # Create proper symlinks
        os.symlink("../../assets", assets_link)
        os.symlink("../../library.bib", bib_link)

print("✓ Symlinks created successfully")
