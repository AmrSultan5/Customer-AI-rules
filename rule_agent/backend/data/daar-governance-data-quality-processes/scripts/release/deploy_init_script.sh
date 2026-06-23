#!/bin/bash

cluster_id=$1
init_script_path=$2
echo "Cluster id is $cluster_id"
echo "Init script path is $init_script_path"

function get_cluster_state(){
  info=$(databricks clusters get $1)
  echo $(echo $info | jq .state -r)
}

function change_cluster_state(){
  # arguments are cluster id and state (RUNNING, TERMINATED supported)
  echo "Changing state of $1 to $2"
  if [ $(get_cluster_state $1) != $2 ];
  then
    if [ $2 = "RUNNING" ];
    then
      databricks clusters start $1
    elif [ $2 = "TERMINATED" ];
    then
      databricks clusters delete $1
    else
      echo "ERROR NOT SUPPORTED STATE"
      exit 1
    fi

    current_state=$(get_cluster_state $1)
    while [ $current_state != $2 ]
    do
      current_state=$(get_cluster_state $1)
      echo "Current state=$current_state, expected state=$2"
      sleep 5
    done
    echo "Sate of $1 changed to $current_state"
  else
    echo "$1 already in state $2"
  fi

}


change_cluster_state $cluster_id "TERMINATED"
echo "Starting deployment of $init_script_path on $cluster_id"
init_scripts_json="[{\"workspace\": {\"destination\": \"${init_script_path}\"}}]"
info=$(databricks clusters get $1)
info=$(echo $info | jq ".init_scripts |= (.+ $init_scripts_json | unique)")
databricks clusters edit --json "$info"
echo "Deployment of $init_script_path on $cluster_id completed"
change_cluster_state $cluster_id "RUNNING"
