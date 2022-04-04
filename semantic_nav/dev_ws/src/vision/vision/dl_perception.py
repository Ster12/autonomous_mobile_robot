import cv2
import numpy as np
import torch
torch.backends.cudnn.benchmark = True
import os
from object_detection import ObjectDetector
from fchardnet_segmentation import FCHarDNetSemanticSegmentation
from pspnet_segmentation import PSPNetSematicSegmentation
from helpers import get_driveable_mask2
import matplotlib.pyplot as plt
import time

class PerceptionSystem(object):
    def __init__(self, config):
        self.config_ = config
        # Load Models
        if(config.model_name == 'fchardnet'):
            self.seg_model_ = FCHarDNetSemanticSegmentation(config.model_path)
        else:
            self.seg_model_ = PSPNetSematicSegmentation(config.model_config_file)

        self.object_detector_ = ObjectDetector(config.model_path_yolo)
        
        # Load perspective transforms
        mtxs = np.load(config.perspective_transform_path)
        self.M_ = mtxs['M']
        self.M_inv_ = mtxs['M_inv']
        
        # Test Detection Models
        print('Segmentation and Detection Models loaded, Testing the models')
        img = cv2.imread("/usr/src/app/dev_ws/src/vision/vision/dolly.png")
        self.h_orig_, self.w_orig_, = self.config_.original_height,self.config_.original_width
        _, _ = self.seg_model_.process_img_driveable(img,[self.config_.original_height,self.config_.original_width],self.config_.drivable_idx)
        _ = self.object_detector_.process_frame(img)
        self.im_hw_ = self.object_detector_.im_hw

        print('Imgs tested')

    def get_driveable(self, drivable_img):
        h,w,_ = drivable_img.shape
        # Warp driveable area
        warped = cv2.warpPerspective(drivable_img, self.M_, (480, 480), flags=cv2.INTER_LINEAR)
        
        # Calculate robot center
        original_center = np.array([[[w/2,h]]],dtype=np.float32)
        warped_center = cv2.perspectiveTransform(original_center, self.M_)[0][0]   
        driveable_contour_mask = get_driveable_mask2(warped, warped_center, self.config_)
        return driveable_contour_mask
    
    def add_detections_birdview(self, preds, driveable_mask):
        h,w,_ = self.object_detector_.im_hw
        h_rate = self.h_orig_/h
        w_rate = self.w_orig_/w
        for pred in preds:
            if(pred[4] > self.object_detector_.conf_thres): # If prediction has a bigger confidence than the threshold
                x = w_rate*(pred[0]+pred[2])/2.0 # Ground middle point
                y = h_rate*pred[3]
                if(pred[5]==0): #person
                    wr = 40
                    hr = 60
                    color = 253#253
                else:
                    wr = 30
                    hr = 90
                    color = 255#255
                pos_orig = np.array([[[x,y]]],dtype=np.float32)
                warped_birdview = cv2.perspectiveTransform(pos_orig, self.M_)[0][0] # Transform middle ground point to birdview
                warped_birdview = np.uint16(warped_birdview)
                cv2.rectangle(driveable_mask, (warped_birdview[0] -int(wr/2), warped_birdview[1]), (warped_birdview[0] +int(wr/2), warped_birdview[1]-hr), color, -1) 
        
    def process_frame(self,img):
        # Semantic Segmentation
        if(self.config_.model_name == 'fchardnet'):
            img_test = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        else:
            img_test = img.copy()
        
        ### TIME 
        start = time.time()
        segmented_img, drivable_img = self.seg_model_.process_img_driveable(img_test,[self.config_.original_height,self.config_.original_width], self.config_.drivable_idx)
        end = time.time()
        print("segmentation: {} seconds".format(end-start))
        # Get bird eye view with driveable area limits

        start = time.time()
        drivable_edge_points_top  = self.get_driveable(drivable_img)
        end = time.time()
        print("warp: {} seconds".format(end-start))
        
        # Object Detection
        preds = self.object_detector_.process_frame(img)
        # if(self.config_.debug):
        #     print('preds: {}'.format(preds))
        #     detections_img = self.object_detector_.draw_rectangles(img, preds)
        #     fig, ax = plt.subplots(figsize=(20, 10))
        #     ax.imshow(detections_img)
        #     plt.show()
        
        # Add Detections to birdview image
        driveable_edge_top_with_objects = drivable_edge_points_top.copy()
        self.add_detections_birdview(preds, driveable_edge_top_with_objects)
        
        return drivable_img, drivable_edge_points_top, preds, driveable_edge_top_with_objects, segmented_img