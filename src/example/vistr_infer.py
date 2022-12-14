# Copyright 2022 Huawei Technologies Co., Ltd
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ============================================================================
"""VisTR infer"""
import torch
import os
import json
import math
import argparse
from PIL import Image
import numpy as np
import pycocotools.mask as mask_util
from src.utils import misc
from src.models.vistr import VistrCom
import mindspore
from mindspore import nn
from mindspore.dataset.vision import py_transforms as T_p
from mindspore import context, Tensor, load_checkpoint, load_param_into_net, ops


def vistr_r50_infer(args_opt):
    """
    vistr resnet50 infer
    """
    context.set_context(mode=context.PYNATIVE_MODE)
    context.set_context(device_id=args_opt.device_target)

    cast = ops.Cast()

    transform = T_p.ToTensor()

    mean = np.array(args_opt.mean)
    std = np.array(args_opt.std)

    num_frames = args_opt.num_frames
    num_ins = args_opt.num_ins

    ann_path = os.path.join(args_opt.dataset_path, "annotations/instances_valid_sub.json")
    folder = os.path.join(args_opt.dataset_path, "val/JPEGImages/")
    videos = json.load(open(ann_path, 'rb'))['videos']

    ms_model = VistrCom(name=args_opt.name,
                        aux_loss=args_opt.aux_loss,
                        dropout=args_opt.drop_out)

    param_dict = load_checkpoint(args_opt.ckpt_file)
    load_param_into_net(ms_model, param_dict)
    weight = np.load("./weights_r50.npy")
    weight = mindspore.Tensor(weight, mindspore.float32)
    ms_model.mask_head.dcn.conv_weight = weight

    vis_num = len(videos)
    result = []

    ms_sigmoid = ops.Sigmoid()
    concat = ops.Concat(axis=0)
    softmax = nn.Softmax(axis=-1)
    expand_dims = ops.ExpandDims()

    result = []
    for i in range(vis_num):
        print("Process video: ", i)
        id_ = videos[i]['id']
        length = videos[i]['length']
        file_names = videos[i]['file_names']

        img_set = []
        if length < num_frames:
            clip_names = file_names*(math.ceil(num_frames/length))
            clip_names = clip_names[:num_frames]
        else:
            clip_names = file_names[:num_frames]
        if clip_names == []:
            continue
        if len(clip_names) < num_frames:
            clip_names.extend(file_names[:num_frames-len(clip_names)])
        for k in range(num_frames):
            im = Image.open(os.path.join(folder, clip_names[k]))
            h = im.size[1]
            w = im.size[0]
            width = int((im.size[0]*300) / im.size[1])
            height = 300
            im = im.resize((width, height), resample=Image.Resampling.BILINEAR)
            im = transform(im)
            im = (im - mean[:, None, None]) / std[:, None, None]
            im = Tensor(im, mindspore.float32)
            im = expand_dims(im, 0)
            img_set.append(im)
        img = concat(img_set)
        images = Tensor(img, mindspore.float32)
        images = images.expand_dims(axis=0)
        if images.shape[-1] <= 700:
            pred, pred_masks = ms_model(images)

            pred_logits = pred[-1, ..., :42]
            pred_boxes = pred[-1, ..., 42:]
            pred_logits = softmax(pred_logits)[0, :, :-1]
            pred_boxes = pred_boxes[0]
            pred_masks = pred_masks[0]

            pred_masks = pred_masks.reshape(36, 10, pred_masks.shape[-2], pred_masks.shape[-1])
            resize_bilinear = ops.ResizeBilinear((h, w))
            pred_masks = resize_bilinear(pred_masks)
            pred_masks = ms_sigmoid(pred_masks).asnumpy() > 0.5

            pred_masks = pred_masks[:length]
            pred_logits = pred_logits.reshape(num_frames, num_ins, pred_logits.shape[-1]).asnumpy()
            pred_logits = pred_logits[:length]
            pred_scores = np.max(pred_logits, axis=-1)
            pred_logits = np.argmax(pred_logits, axis=-1)
            for m in range(num_ins):
                if pred_masks[:, m].max() == 0:
                    continue
                score = pred_scores[:, m].mean()
                category_id = np.argmax(np.bincount(pred_logits[:, m]))
                instance = {'video_id': id_, 'score': float(score), 'category_id': int(category_id)}
                segmentation = []
                for n in range(length):
                    if pred_scores[n, m] < 0.001:
                        segmentation.append(None)
                    else:
                        mask = (pred_masks[n, m]).astype('uint8')
                        rle = mask_util.encode(np.array(mask[:, :, np.newaxis], order='F'))[0]
                        rle["counts"] = rle["counts"].decode("utf-8")
                        segmentation.append(rle)
                instance['segmentations'] = segmentation
                result.append(instance)
    with open("results/results.json", 'w', encoding='utf-8') as f:
        json.dump(result, f)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VisTR_r50 Train.")
    # dataset
    parser.add_argument("--dataset_path", type=str, default="/data0/VOS")
    parser.add_argument("--ckpt_file", type=str, default="./vistr_r50_all.ckpt")
    parser.add_argument("--device_target", type=int, default=2)
    parser.add_argument("--mean", type=list, default=[0.485, 0.456, 0.406], help='use for img normalize')
    parser.add_argument("--std", type=list, default=[0.229, 0.224, 0.225], help='usr for img normalize')
    parser.add_argument("--num_frames", type=int, default=36, help='number of frame')
    parser.add_argument("--num_ins", type=int, default=10, help='number of instance in the frame')
    # model
    parser.add_argument("--name", type=str, default='ResNet50', help='choose embedingtype, ResNet50 or ResNet101')
    parser.add_argument('--aux_loss', type=bool, default=True, help='Calculate the intermediate layer loss')
    parser.add_argument('--drop_out', type=float, default=0.0)

    parser.add_argument("--save_path", type=str, default="./outfile", help='path of saving output file')

    args = parser.parse_known_args()[0]
    vistr_r50_infer(args)
