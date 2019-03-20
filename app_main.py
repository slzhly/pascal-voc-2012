import sys, os
import numpy as np
import scipy as sp
import pickle
from PIL import Image

import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader

from torchvision import transforms
import torchvision.models as models
from sklearn.metrics import average_precision_score

from flask import Flask, render_template, request, g

import matplotlib.pyplot as plt
    
torch.manual_seed(0)

class CustomNet(nn.Module):
    def __init__(self, base_net=None):
        super().__init__()
        self.base_net = base_net
        self.pool = nn.AdaptiveAvgPool3d((3,224,224))
        
    def forward(self, x):
        self.base_net.eval()
        x_mod = self.pool(x)
        with torch.no_grad():
            out = self.base_net(x_mod)
        return out

class Backend(object):
    def __init__(self, imgs_dir='VOC2012/JPEGImages/', pred_dir='logs/attempt1/', models_dir='logs/attempt1/'):
        self.imgs_dir = imgs_dir
        self.pred_dir = pred_dir
        self.models_dir = models_dir
        self.model = self._load_default_model()
        self.img_paths = self._load_img_paths()
        self.val_order = self._load_val_order()
        self.labels_dict = self.get_labels_dict()
        self.predict_img_counter = 0
        
    def get_labels_dict(self):
        return {
            0: 'aeroplane' ,
            1: 'bicycle' ,
            2: 'bird' ,
            3: 'boat' ,
            4: 'bottle' ,
            5: 'bus' ,
            6: 'car' ,
            7: 'cat' ,
            8: 'chair' ,
            9: 'cow' ,
            10: 'diningtable' ,
            11: 'dog' ,
            12: 'horse' ,
            13: 'motorbike' ,
            14: 'person' ,
            15: 'pottedplant' ,
            16: 'sheep' ,
            17: 'sofa' ,
            18: 'train' ,
            19: 'tvmonitor'
        }
        
    def _load_default_model(self):
        return self.load_model('stop_lr0.001_sc0.001_model_BCE_40_0.1131')
    
    def _load_val_order(self):
        return np.load('logs/val_order.npy')
        
    def _load_img_paths(self):    
        image_paths = []
        image_path_file = 'VOC2012/ImageSets/Main/val.txt' 
        with open(image_path_file) as f:
            for image_path in f.readlines():
                candidate_path = image_path.split(' ')[0].strip('\n')
                image_paths.append(candidate_path)
        return image_paths
    
    def load_model(self, model_name):
        model = models.resnet18(pretrained=True)
        model.fc = nn.Linear(512, 20)
        model.load_state_dict(torch.load(self.models_dir + model_name + '.pt'))
        model = CustomNet(model)
        return model

    def load_img(self, idx):
        if type(idx) != int:
            idx = int(idx[0])
        print(idx, self.predict_img_counter)
        return self.imgs_dir + self.img_paths[idx] + '.jpg'
    
    def pred_from_path(self, file_path):
        img = Image.open(file_path)
        scores = self.get_prediction(img)
        output = []
        for i, score in enumerate(scores):
            if score > 0.5:
                output.append(self.labels_dict[i])
        return scores.cpu().numpy(), output

                
    def get_prediction(self, x):
        scores = self.model(x)
        scores = scores.cpu().numpy()
        preds = []
        for i in scores:
            pred = 0
            if i > 0.5:
                pred = 1
            preds.append(pred)
        return preds
        
    def main(self):
        pass
        
def load_pickle(file_path='logs/attempt1/pred_BCE_40.pkl'):
    with open(file_path, 'rb') as f:
        ret = pickle.load(f)
    return ret
    
def get_preds_and_gt(pickled, output_type='numpy'):
    preds, gt = [], []
    for pair in pickled:
        preds.append(pair['pred'])
        gt.append(pair['target'])
    pred_tensor = torch.cat(preds, dim=0)
    gt_tensor = torch.cat(gt, dim=0)
    if output_type == 'numpy':
        return pred_tensor.cpu().numpy(), gt_tensor.cpu().numpy()
    return pred_tensor, gt_tensor

def load_scores_and_gt(file_path='logs/attempt1/pred_BCE_40.pkl'):
    return get_preds_and_gt(load_pickle(file_path))
    
def rank_by_class(scores, col=0):
    out = np.copy(scores)
    new_order = out[:,col].argsort()[::-1]
    return out[new_order], new_order
    
def _test_pickle_and_rank():
    temp = load_pickle()
    preds, gt = get_preds_and_gt(temp, 'numpy')
    class_0, class_0_idx = rank_by_class(preds, 0)
    class_1, class_1_idx = rank_by_class(preds, 1)
    print(class_0[:10,0], class_0_idx[:10])
    print(class_1[:10,1], class_1_idx[:10])
    
def get_tail_acc(sorted_scores, sorted_gt, t_min, t_max, t_num):
    t_vals = np.linspace(t_min, t_max, t_num, endpoint=False)
    tail_accs = []
    for t_val in t_vals:
        tp = 0
        fp = 0
        start = True
        for (score, target) in zip(sorted_scores, sorted_gt):
            pred = 0
            if score > t_val:
                pred = 1
                if pred == target:
                    tp += 1
                else:
                    fp += 1
        tail_acc = 0
        if tp+fp > 0:
            tail_acc = tp/(tp+fp)
        #print(t_val, tp, fp)
        tail_accs.append(tail_acc)
        
    return tail_accs
    
def get_mAP(scores, gt):
    mAP = 0
    for i in range(scores.shape[0]):
        pred = np.array([1 if scores[i,j] > 0.5 else 0 for j in range(scores.shape[1])])
        AP = average_precision_score(pred, gt[i])
        mAP += AP
    mAP /= scores.shape[0]
    return mAP
    
def _test_tail_acc():
    pickled = load_pickle()
    scores, gt = get_preds_and_gt(pickled, 'numpy')
    sorted_scores, idx_order = rank_by_class(scores, 0)
    t_max = np.max(scores)
    print(t_max)
    tail_accs = get_tail_acc(sorted_scores[:,0], gt[idx_order][:,0], 0.5, t_max, 10)
    print(tail_accs)
                
def get_tail_acc_classwise(scores, gt, t_min=0.5, t_num=10):
    t_max = np.max(scores)
    tail_accs = []
    t_vals = np.linspace(t_min, t_max, t_num, endpoint=False)
    for i in range(20):
        sorted_scores, idx_order = rank_by_class(scores, i)
        tail_accs_i = get_tail_acc(sorted_scores[:50,i], gt[idx_order][:50,i], t_min, t_max, t_num)
        tail_accs.append(tail_accs_i)
    return tail_accs, t_vals
    
def _plot_tail_acc(file_path):
    pickled = load_pickle(file_path)
    scores, gt = get_preds_and_gt(pickled, 'numpy')
    tail_accs, t_vals = get_tail_acc_classwise(scores, gt, 0.5, 10)
    tail_accs = np.array(tail_accs)
    ave_tail_accs = np.mean(tail_accs, axis=0)
    plt.figure()
    plt.plot(t_vals, ave_tail_accs, 'b', t_vals, ave_tail_accs, 'ro')
    plt.xticks(t_vals)
    plt.title('Average of classwise tailaccs over top-50 ranked images in each class')
    plt.ylabel('Tailaccs')
    plt.xlabel('t value')
    plt.show()
    
class MyFlask(Flask):
    def __init__(self, name, **kwargs):
        super().__init__(name, static_folder=kwargs['static_folder'], static_url_path=kwargs['static_url_path'])
        self.predict_img_counter = 0

app = MyFlask(__name__, static_folder='.', static_url_path='')
backend = Backend()
predict_img_counter = 0
max_img_counter = backend.val_order.shape[0]

@app.route('/')
def home():
    return render_template('home.html')
  
@app.route('/predict', methods=['GET'])
def predict():
    try:
        btn_val = request.form['btn']
    except:
        file_path = backend.load_img(app.predict_img_counter)
        return render_template('predict.html', img_src=file_path)
    if btn_val == 'Next':
        app.predict_img_counter += 1
        app.predict_img_counter %= max_img_counter
        file_path = backend.load_img(app.predict_img_counter)
        return render_template('predict.html', img_src=file_path)
    elif btn_val == 'Previous':
        if app.predict_img_counter == 0:
            app.predict_img_counter -= 1
        else:
            app.predict_img_counter = max_img_counter-1
        file_path = backend.load_img(app.predict_img_counter)
        return render_template('predict.html', img_src=file_path)
    elif btn_val == 'Submit':
        file_path = request.form['file_path']
        output = backend.pred_from_path(file_path)
        return render_template('predict_output.html', scores=output[0], pred=output[1])
        
    
@app.route('/browse')
def browse():
    return render_template('browse.html')
    
if __name__ == '__main__':
    app.run(debug=True, use_reloader=True)
    
    #_plot_tail_acc('logs/attempt1/pred_BCE_40.pkl')
    #_plot_tail_acc('logs/attempt2/pred_NB_40.pkl')
        