#!/bin/bash
pip install {{package}} --index-url=https://pypi.org/simple --extra-index-url=https://${FEED_TOKEN}@pkgs.dev.azure.com/{{project}}/_packaging/{{feed}}/pypi/simple/ --extra-index-url=https://${FEED_TOKEN}@pkgs.dev.azure.com/{{project}}/_packaging/daar-datamesh-common/pypi/simple/ --extra-index-url=https://${FEED_TOKEN}@pkgs.dev.azure.com/{{project}}/_packaging/daar-datamesh-data-io/pypi/simple/ --extra-index-url=https://${FEED_TOKEN}@pkgs.dev.azure.com/{{project}}/_packaging/daar-datamesh-datalake-kbi/pypi/simple/ --extra-index-url=https://${FEED_TOKEN}@pkgs.dev.azure.com/{{project}}/_packaging/daar-datamesh-transformation/pypi/simple/
sudo apt-get install curl autoconf automake libtool pkg-config --yes
git clone https://github.com/openvenues/libpostal
cd libpostal
./bootstrap.sh
./configure --datadir=/databricks/driver/libpostal
make -j4
sudo make install
sudo ldconfig
pip install postal==1.1.10