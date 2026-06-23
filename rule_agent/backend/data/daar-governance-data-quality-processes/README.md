[[_TOC_]]

# Introduction
Application that uses data-mesh.transformation-lib to curate datasets and load into central repo.

# Getting Started
It is auto deployed to required clusters via the pipelines.

# Contribute
Main logic is in the config files, located at /datamesh_datalake_curated/configs/processes the rest is only boilerplate

# Setup

## Cloning the Repository
Clone the repository and move to its directory
```bash
git clone https://CCHBC@dev.azure.com/CCHBC/CCH%20SAFe%20Portfolio/_git/daar-datamesh-datalake-curated # Use HTTPS or SSH - whichever is preferred
cd daar-datamesh-datalake-curated/
```

## Python Environment
It is recommended to use Python Virtual Environment - `pyenv` is a great tool for managing Python Versions and Environments.

1. Install `pyenv` - check the installation guide on _pyenv's_ GitHub page -  More here: https://github.com/pyenv/pyenv#automatic-installer

1. Create a new Python Environment:
    ```bash
    pyenv install 3.8.8  
    ```
1. Make it a default for this project:
    ```bash
    rm .python-version # File holds local version
    pyenv local 3.8.8
    ```
    _(Optional)_ If you want to switch back to system, use this command:
    ```bash
    pyenv local system
    ```
1. Test your new Python environment:
    ```bash
    pyenv which python
    python -V 
    pip -V
    ```
    Expected output:
    ```shell script
    >> /home/macbeat/.pyenv/versions/3.8.8/bin/python
    >> Python 3.8.8
    >> pip 20.2.3 from /home/macbeat/.pyenv/versions/3.8.8/lib/python3.8/site-packages/pip (python 3.8)
    ```
1. _(Optional)_ Upgrade `pip`:
    ```shell script
    pip install --upgrade pip
    ```
1. _(Optional)_ It is also good practice from time to time check your libraries dependencies
   and remove overlapping imports in `requirements.txt` and `development_requirements.txt`
   ```shell script
   pip install pip-chill
   pip-chill -v
   ```

## Java
Install Java 8 because it will be required by `PySpark` dependency. If using Linux/WSL environment, use `apt` to install one:
```bash
sudo apt-get install openjdk-8-jdk
```

## Spark and Hadoop
In order for the local _PySpark_ instalation to work (when developing, testing, etc.), a standalone, local instance of both Spark and Hadoop have to be setup.
1. Start by creating two directories - one for Spark and one for Hadoop
    ```bash
    mkdir -p /opt/{spark,hadoop} 
    ```

1. Download and extract Spark:
    ```bash
    wget https://archive.apache.org/dist/spark/spark-3.1.2/spark-3.1.2-bin-without-hadoop.tgz -P /opt/spark # Download zipped Spark
    tar -xf /opt/spark/spark-3.1.2-bin-without-hadoop.tgz -C /opt/spark # Unzip
    rm /opt/spark/spark-3.1.2-bin-without-hadoop.tgz # Remove archive
    ```

1. Download and extract Hadoop:
    ```bash
    wget https://ftp.cc.uoc.gr/mirrors/apache/hadoop/common/hadoop-3.3.1/hadoop-3.3.1.tar.gz -P /opt/hadoop # Download zipped Hadoop
    tar -xf /opt/hadoop/hadoop-3.3.1.tar.gz -C /opt/hadoop # Unzip
    rm /opt/hadoop/hadoop-3.3.1.tar.gz # Remove archive
    ```

1. Set environment variables required for both Spark and Hadoop to run. Edit the `.bashrc` file and add at the end the following lines:
    ```bash
    export SPARK_HOME='/opt/spark/spark-3.1.2-bin-without-hadoop'
    export HADOOP_HOME='/opt/hadoop/hadoop-3.3.1'
    export JAVA_HOME='/usr/lib/jvm/java-1.8.0-openjdk-amd64' # Double check if correct for your setup

    HADOOP_LIB_PATH=${HADOOP_HOME}/share/hadoop/
    export SPARK_DIST_CLASSPATH=${HADOOP_LIB_PATH}common/lib/*:${HADOOP_LIB_PATH}common/*:${HADOOP_LIB_PATH}hdfs/*:${HADOOP_LIB_PATH}hdfs/lib/*:${HADOOP_LIB_PATH}mapreduce/*:${HADOOP_LIB_PATH}mapreduce/lib/*:${HADOOP_LIB_PATH}tools/lib/*
    ```

1. Save `.bashrc` file and reload shell:
    ```bash
    source ~/.bashrc
    ```

## Project dependencies

1. Create virtual environment
    ```bash
    python -m venv venv
    ```

1. Activate newly created virtual environment
    ```bash
    source venv/bin/activate
    ```

1. Copy `pip.conf` to venv directory to configure access to private pip feed where `data-mesh.common` library is kept. If you created your virtual env named `venv` in the project directory, use this command:
    ```bash
    cp pip.conf venv/
    ```

1. Generate PAT (Personal Access Token) which allows the internal libraries to be installed on your local machine. A tutorial on how to do it can be found [here](https://learn.microsoft.com/en-us/azure/devops/organizations/accounts/use-personal-access-tokens-to-authenticate?view=azure-devops&tabs=Windows#create-a-pat) <br>
**Note:** For accessing the packages the scope `Packaing:Read` should be enough - there is no need to grant too many scopes to the token.

1. Edit the `pip.conf` file copied into the virtual environment and add the PAT in the correct place:
    ```bash
    extra-index-url=https://<PAT>@pkgs.dev.azure.com/CCHBC/f6799d46-e250-45e0-8475-5662f88b0a2d/_packaging/daar-datamesh-common/pypi/simple/
    ```
    If your PAT is _abc1234_, then the URL should look like this:
    ```bash
    https://abc1234@pkgs.dev.azure.com/CCHBC/f6799d46-e250-45e0-8475-5662f88b0a2d/_packaging/daar-datamesh-common/pypi/simple/
    ```

1. Install dotnet (https://docs.microsoft.com/en-us/dotnet/core/install/linux-ubuntu)

1. Install all required Python dependencies with this command:
    ```bash
    pip install -r development_requirements.txt
    ```

# How to run the tests?
Tests can be executed inside your IDE or via commandline.

Follow this steps to execute unit tests via commandline:
1. Go to project root dir.
2. Execute the following command:
    ```shell script
    sh scripts/run_all_unit_tests.sh
    ```

# How to build package?
1. Go to project root dir.
2. Execute the following command:
    ```shell script
    python setup.py bdist_wheel
    ```
3. Project package (precisely: `.whl` file) will be located in `dist` directory.

# How to install and use `pre-commit` for automated code fixes on local dev environment?
1. `pre-commit` executes scripts/checks configured in [.pre-commit-config.yaml](.pre-commit-config.yaml) when `git commit` is executed.
    > :exclamation: **`pre-commit` checks only file that were changes in a given commit!** To run a "full scan" execute: `pre-commit run --all-files`
1. `pre-commit` can be installed using `pip install` command. Run:
    ```shell script
    pip install -r development_requirements.txt
    ```
1. Go to the project root directory and install project related `pre-commit` scripts/checks by running:
    ```shell script
    pre-commit install --allow-missing-config
    ```
1. When one of `pre-commit` steps fail, then `git commit` also fails (`git commit` triggers `pre-commit` scripts/checks). Example output:
    ```shell script
    Check Yaml...........................................(no files to check)Skipped
    Check Xml............................................(no files to check)Skipped
    Fix End of Files.........................................................Passed
    Fix requirements.txt.................................(no files to check)Skipped
    Trim Trailing Whitespace.................................................Failed
    - hook id: trailing-whitespace
    - exit code: 1
    - files were modified by this hook

    Fixing README.md

    black................................................(no files to check)Skipped
    ```
1. Some of `pre-commit` checks can fix the code automatically (for example: `black` code formatter, [more info about black here](https://github.com/psf/black)) - then just include those changes to the git index once again: `git add <file or dir path>`
1. It may also happen that some manual fixes are needed based on the `pre-commit` output. If so, apply fixes manually and run: `git add <file or dir path>`

# How to clean up the git repository?

## Git Cheatsheet
- https://www.atlassian.com/git/tutorials/atlassian-git-cheatsheet
- https://about.gitlab.com/images/press/git-cheat-sheet.pdf

## Remove untracked files
1. Go to project root dir.
2. Execute the following command and review the list of files and directories that are about to be deleted:
    ```shell script
    git clean -fdx --dry-run --exclude '.idea/' --exclude '.vscode/' --exclude '.python-version' --exclude '*.env' --exclude '*.ipynb' --exclude '*.sh' --exclude '*.ps1' --exclude '*.py' .
    ```
3. If something needs to be excluded from deletion, add additional parameter: `--exclude 'my/important/file.txt'`
4. If the list of files/directories to be deleted looks fine, execute the above command without `--dry-run` param.

See: https://git-scm.com/docs/git-clean

## Remove obsolete branches from local copy

```shell script
git fetch -p -a && git branch -vv | awk '/: gone]/{print $1}' | xargs git branch -D
```

# How to deploy lib to DataBricks Cluster in manual way

**Manual deployment should be exceptional activity and deployment should be executed via deployment pipelines**

1. Ensure that Databricks support Python 3.8.x
2. Install all required libraries from requirements.txt  (Right now there is no easy method to do it in script way). Go to
    - Go to  Libraries tab in cluster
    - Click Install New
    - Select PyPI and copy-paste libraries from requirements.txt (one by one)  
3. Install databricks-cli according to https://docs.databricks.com/dev-tools/cli/index.html
4. Deploy library using deploy.ps1: deploy.ps1
5. Install deployed package using "Libraries" tab in cluster
    - Go to Libraries tab in cluster
    - Click Install New
    - Select DBFS and Python Whl
    - Provide dbfs path to wheel package


# Local variables set-up
```
PYTHONPATH=$PYTHONPATH;${workspaceFolder}
HTTP_PROXY=
HTTPS_PROXY=
NO_PROXY=

SPARK_HOME=c:\spark
HADOOP_HOME=c:\hadoop321
HADOOP_LIB_PATH=${HADOOP_HOME}\share\hadoop
SPARK_DIST_CLASSPATH=${HADOOP_LIB_PATH}\common\lib\*;${HADOOP_LIB_PATH}\common\*;${HADOOP_LIB_PATH}\hdfs\*;${HADOOP_LIB_PATH}\hdfs\lib\*;${HADOOP_LIB_PATH}\mapreduce\*;${HADOOP_LIB_PATH}\mapreduce\lib\*;${HADOOP_LIB_PATH}\tools\lib\*
```

# Others

## Certificates install

To install certificate on kubuntu/ubuntu linux box please execute following steps as `root`
- To export certificate from Windows please
  - Open `certmgr.exe`
  - Select certificate, move to **Details** and select **Copy To file**. Use **Base-64 encoded X.509**
  - Rename file to have `crt` suffix
- Copy certificate to `usr/local/share/ca-certificates` directory  
- Execute `update-ca-certificates` to register certificate
