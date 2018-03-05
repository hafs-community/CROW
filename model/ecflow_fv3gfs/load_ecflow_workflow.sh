#! /bin/bash

set -ue

# Get the directory in which this script resides.  We'll assume the
# yaml files are there:
dir0=$( dirname "$0" )
here=$( cd "$dir0" ; pwd -P )

export WORKTOOLS_VERBOSE=NO

crowdir=$( cd ../../ ; pwd -P )

# Make sure this directory is in the python path so we find worktools.py:
export PYTHONPATH=$here:$crowdir:${PYTHONPATH:+:$PYTHONPATH}

# Parse arguments:
if [[ "$1" == "-v" ]] ; then
    export WORKTOOLS_VERBOSE=YES
    shift 1
fi
export CONFIGDIR="$1"

if [[ ! -d /usrx/local || -e /etc/redhat-release ]] ; then
   echo "ERROR: This script only runs on WCOSS Cray" 1>&2
   exit 1
fi

if ( ! which ecflow_client > /dev/null 2>&1 ) ; then
    echo "ERROR: There is no ecflow_client in your \$PATH.  Load the ecflow module."
    exit 1
fi

if [[ "${ECF_ROOT:-Q}" == Q ]] ; then
    echo "ERROR: You need to set \$ECF_ROOT"
    exit 1
fi

if [[ "${ECF_HOME:-Q}" == Q ]] ; then
    echo "ERROR: You need to set \$ECF_HOME.  I suggest \$ECF_ROOT/submit"
    exit 1
fi

if [[ "${ECF_HOST:-Q}" == Q ]] ; then
    echo "ERROR: You need to set \$ECF_HOST."
    exit 1
fi

if [[ "${ECF_PORT:-Q}" == Q ]] ; then
    echo "ERROR: You need to set \$ECF_PORT.  See /usrx/local/sys/ecflow/assigned_ports.txt"
    exit 1
fi

export ECF_HOME="${ECF_HOME:-$ECF_ROOT/submit}"

if [[ "${WORKTOOLS_VERBOSE:-NO}" == YES ]] ; then 
    echo "load_ecflow_workflow.sh: verbose mode"
fi

echo 'ecFlow server settings:'
echo "   port: $ECF_PORT"
echo "   root: $ECF_ROOT"
echo "   home: $ECF_HOME"
echo "   host: $ECF_HOST"

set +e
if ( ! which python3 > /dev/null 2>&1 || \
     ! python3 -c 'import yaml ; f{"1+1"}' > /dev/null 2>&1 ) ; then
    python36=/gpfs/hps3/emc/nems/noscrub/Samuel.Trahan/python/3.6.1-emc/bin/python3.6
else
    python36="$( which python3 )"
fi
set -e

tmpfile=${TMPDIR:-/tmp}/find-expdir.$RANDOM.$RANDOM.$$

maybe_verbose_source() {
    if [[ "${WORKTOOLS_VERBOSE:-NO}" == YES ]] ; then
	echo "$1: source"
	source "$1"
    else
	source "$1" > /dev/null 2>&1
    fi
}

make_yaml_files() {
    if [[ "${WORKTOOLS_VERBOSE:-NO}" == YES ]] ; then
	set -x
    fi

    # NOTE: Sourcing config.base clobbers the ecflow variables, so we
    # must do it in a subshell.
    set +ue
    maybe_verbose_source "$CONFIGDIR"/config.base 
    set -ue

    if [[ "${WORKTOOLS_VERBOSE:-NO}" == YES ]] ; then
	set -x
    fi

    echo "EXPDIR=\"$EXPDIR\"" > "$tmpfile"

    mkdir -p "$EXPDIR"/logs
    
    set +ue
    ( maybe_verbose_source "$CONFIGDIR"/config.earc ;
      echo "export NMEM_EARCGRP=\"$NMEM_EARCGRP\"" >> "$tmpfile" )
    ( maybe_verbose_source "$CONFIGDIR"/config.efcs ;
      echo "export NMEM_EFCSGRP=\"$NMEM_EFCSGRP\"" >> "$tmpfile" ;
      echo "export ENKF_layout_x=\"$layout_x\"" >> "$tmpfile" ;
      echo "export ENKF_layout_y=\"$layout_y\"" >> "$tmpfile" ;
      echo "export ENKF_WRITE_GROUP=\"$WRITE_GROUP\"" >> "$tmpfile" ;
      echo "export ENKF_WRTTASK_PER_GROUP=\"$WRTTASK_PER_GROUP\"" >> "$tmpfile" )
    ( maybe_verbose_source "$CONFIGDIR"/config.eobs ;
      echo "export NMEM_EOMGGRP=\"$NMEM_EOMGGRP\"" >> "$tmpfile" )
    ( maybe_verbose_source "$CONFIGDIR"/config.fcst ;
      echo "export layout_x=\"$layout_x\"" >> "$tmpfile" ;
      echo "export layout_y=\"$layout_y\"" >> "$tmpfile" ;
      echo "export WRITE_GROUP=\"$WRITE_GROUP\"" >> "$tmpfile" ;
      echo "export WRTTASK_PER_GROUP=\"$WRTTASK_PER_GROUP\"" >> "$tmpfile" )
    set -ue

    source "$tmpfile"

    $python36 -c "import worktools ; worktools.make_yaml_files('$here','$EXPDIR')"
}

if ( ! ( make_yaml_files ) ) ; then
    echo "Failed to make YAML files"
    exit 1
fi

source "$tmpfile"
rm -f "$tmpfile"

if [[ "${WORKTOOLS_VERBOSE:-NO}" == YES ]] ; then
    set -x
fi

if [[ "${WORKTOOLS_VERBOSE:-NO}" == YES ]] ; then
    /ecf/devutils/server_check.sh "$ECF_ROOT" "$ECF_PORT" || true
else
    /ecf/devutils/server_check.sh "$ECF_ROOT" "$ECF_PORT" > /dev/null 2>&1 || true
fi

if ( ! ecflow_client --ping ) ; then
    echo "Could not connect to ecflow server.  Aborting."
    exit 1
fi

if ( ! ecflow_client --get=/totality_limit > /dev/null 2>&1 ) ; then
    ecflow_client --load ./totality_limit.def
fi

$python36 -c "import worktools ; worktools.create_and_load_ecflow_workflow('$EXPDIR',begin=False)"






