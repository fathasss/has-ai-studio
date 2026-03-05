import os
import shutil
import sys

def cleanup_broken_paths(project_dir):
    print(f"Starting cleanup in: {project_dir}")
    if not os.path.exists(project_dir):
        print("Project directory does not exist.")
        return

    broken_extensions = [".py", ".js", ".ts", ".jsx", ".tsx", ".css", ".html", ".env", ".json"]
    removed_count = 0

    for root, dirs, files in os.walk(project_dir):
        for d in list(dirs):
            if any(d.lower().endswith(ext) for ext in broken_extensions):
                full_path = os.path.join(root, d)
                print(f"Removing broken directory: {full_path}")
                try:
                    shutil.rmtree(full_path)
                    dirs.remove(d) # Don't descend into removed dir
                    removed_count += 1
                except Exception as e:
                    print(f"Error removing {full_path}: {e}")

    print(f"Cleanup finished. Removed {removed_count} directories.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python cleanup_sprint.py <project_dir>")
    else:
        cleanup_broken_paths(sys.argv[1])
