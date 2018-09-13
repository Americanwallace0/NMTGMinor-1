from __future__ import division

import math
import torch
from torch.autograd import Variable

import onmt

class Dataset(object):
    '''
    batchSize is now changed to have word semantic (probably better)
    '''
    def __init__(self, srcData, tgtData, batchSize, gpus,
                 volatile=False, data_type="text", balance=False, max_seq_num=128):
        self.src = srcData
        self._type = data_type
        if tgtData:
            self.tgt = tgtData
            assert(len(self.src) == len(self.tgt))
        else:
            self.tgt = None
        self.cuda = (len(gpus) > 0)
        self.fullSize = len(self.src)
        self.n_gpu = len(gpus)

        self.batchSize = batchSize
        #~ self.numBatches = math.ceil(len(self.src)/batchSize)
        self.volatile = volatile
        
        self.balance = balance
        self.max_seq_num = max_seq_num 
        
        # if self.balance:
        self.allocateBatch()
        self.cur_index = 0
        self.batchOrder = None
        # else:
            # self.numBatches = math.ceil(len(self.src)/batchSize)

    #~ # This function allocates the mini-batches (grouping sentences with the same size)
    def allocateBatch(self):
            
        # The sentence pairs are sorted by source already (cool)
        self.batches = []
        
        cur_batch = [0]
        cur_batch_size = self.tgt[0].size(0)
        cur_batch_sizes = [self.tgt[0].size(0)]
        
        i = 1
        #~ for i in range(1, self.fullSize):
        while i <  self.fullSize:
            
            sentence_length = self.tgt[i].size(0)
            #~ print(sentence_length)
            
            oversized_batch = False
            
            if ( max(max(cur_batch_sizes), sentence_length) * (len(cur_batch)+1)> self.batchSize ) or len(cur_batch) == self.max_seq_num:
                oversized_batch = True
            
            # if the current length makes the batch exceeds
            # the we create a new batch
            #~ if ( cur_batch_size + sentence_length > self.batchSize ) or len(cur_batch) == self.max_seq_num:
            if oversized_batch:
                #~ self.batches.append(cur_batch) # add this batch into the batch list
                #~ cur_batch = [] # reset the current batch
                #~ cur_batch_size = 0
                #~ cur_batch_sizes = []
                rescaled_size = max(
                                    8 * (len(cur_batch) // 8),
                                    len(cur_batch) % 8,
                                )
                
                current_size = len(cur_batch)
                batch_ = cur_batch[:rescaled_size]
                self.batches.append(batch_)
                
                cur_batch = [] # reset the current batch
                cur_batch_size = 0
                cur_batch_sizes = []
                i = i - current_size + rescaled_size
                
            
            cur_batch.append(i)
            cur_batch_size += sentence_length
            cur_batch_sizes.append(sentence_length)
            i = i + 1 
                
            
        # catch the last batch
        if len(cur_batch) > 0:
            self.batches.append(cur_batch)
        
        self.numBatches = len(self.batches)
                
    def _batchify(self, data, align_right=False,
                  include_lengths=False, dtype="text"):
        lengths = [x.size(0) for x in data]
        max_length = max(lengths)
        out = data[0].new(len(data), max_length).fill_(onmt.Constants.PAD)
        for i in range(len(data)):
            data_length = data[i].size(0)
            offset = max_length - data_length if align_right else 0
            out[i].narrow(0, offset, data_length).copy_(data[i])
        if include_lengths:
            return out, lengths 
        else:
            return out
        
                
                
    def __getitem__(self, index):
        assert index < self.numBatches, "%d > %d" % (index, self.numBatches)
        
        batch = self.batches[index]
        srcData = [self.src[i] for i in batch]
        srcBatch, lengths = self._batchify(
            srcData,
            align_right=False, include_lengths=True, dtype=self._type)

        if self.tgt:
            tgtData = [self.tgt[i] for i in batch]
            tgtBatch = self._batchify(
                        tgtData,
                        dtype="text")
        else:
                tgtBatch = None
        

        def wrap(b, dtype="text"):
            if b is None:
                return b
            #~ print (b)
            #~ b = torch.stack(b, 0)
            #~ b = b.t().contiguous()
            b = b.contiguous()
           
            return b

        srcTensor = wrap(srcBatch, self._type)
        tgtTensor = wrap(tgtBatch, "text")
        
        
        return [srcTensor, tgtTensor]
       

    def __len__(self):
        return self.numBatches
        
    def create_order(self, random=True):
        
        if random:
            self.batchOrder = torch.randperm(self.numBatches)
        else:
            self.batchOrder = torch.arange(self.numBatches).long()
        self.cur_index = 0
        
        return self.batchOrder
        
    def next(self, curriculum=False, reset=True, split_sizes=1):
        
         # reset iterator if reach data size limit
        if self.cur_index >= self.numBatches:
            
            if reset:
                self.cur_index = 0
            else: return None
        
        if curriculum or self.batchOrder is None:
            batch_index = self.cur_index
        else:
            batch_index = self.batchOrder[self.cur_index]
            
        batch = self[batch_index]
        
        # move the iterator one step
        self.cur_index += 1
        
        #split that batch to number of gpus
        
        samples = []
        split_size = int(math.ceil(batch[0].size(1) / self.n_gpu))  
        
        # maybe we need a more smart splitting function ?
        
        if batch[1] is not None:
            batch_split = zip(batch[0].split(split_size, dim=1), 
                              batch[1].split(split_size, dim=1))
                              
            
            batch_split = [ [b[0], b[1]] for i, b in enumerate(batch_split) ] 
        else:
            batch_split = zip(batch[0].split(split_size, dim=1))
                              
            
            batch_split = [ [b[0], None] for i, b in enumerate(batch_split) ] 
       
        return batch_split
    

    def shuffle(self):
        data = list(zip(self.src, self.tgt))
        self.src, self.tgt = zip(*[data[i] for i in torch.randperm(len(data))])
        
    def set_index(self, iteration):
        
        assert iteration >= 0 and iteration < self.numBatches
        self.cur_index = iteration

# class AugmentedDataset(object):
