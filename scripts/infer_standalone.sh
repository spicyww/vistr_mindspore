echo "================================================================================================"
echo "Please run the script as: "
echo "bash eval_standalone.sh [PROJECT_PATH] [DATA_PATH] [MODEL_PATH]"
echo "For example: bash infer_standalone.sh /home/vistr /home/publicfile/VOS vistr_r50.ckpt"
echo "================================================================================================"
set -e
if [ $# -lt 2 ]; then
  echo "Usage: bash infer_standalone.sh [PROJECT_PATH] [DATA_PATH] [MODEL_PATH]"
exit 1
fi

PYTHON_PATH=$1
DATA_PATH=$2
MODEL_PATH=$3

export PYTHONPATH=$PYTHON_PATH
python $PYTHON_PATH/src/example/vistr_r50_infer.py --dataset_path $DATA_PATH \
    --pretrained_model $MODEL_PATH >  eval_result.log 2>&1

