import sys
import torch
from torch import cuda
from transformers import *
from torch import nn
from torch.autograd import Variable
from holder import *
from util import *

# encoder with Elmo
class BertEncoder(torch.nn.Module):
	def __init__(self, opt, shared):
		super(BertEncoder, self).__init__()
		self.opt = opt
		self.shared = shared

		self.zero = Variable(torch.zeros(1), requires_grad=False)
		self.zero = to_device(self.zero, self.opt.gpuid)
		
		print('loading BERT model...')
		self.bert = self._get_bert(self.opt.bert_type)

		for n in self.bert.children():
			for p in n.parameters():
				p.skip_init = True
				p.is_bert = True	# tag as bert fields

		# if to lock bert
		if opt.fix_bert == 1:
			for n in self.bert.children():
				for p in n.parameters():
					p.requires_grad = False

		#self.customize_cuda_id = self.opt.gpuid
		#self.fp16 = opt.fp16 == 1	# this is no longer needed


	def _get_bert(self, key):
		model_map={"bert-base-uncased": (BertModel, BertTokenizer),
			"roberta-base": (RobertaModel, RobertaTokenizer),
			"roberta-large": (RobertaModel, RobertaTokenizer)}
		model_cls, _ = model_map[key]
		return model_cls.from_pretrained(key)


	def forward(self, tok_idx):
		tok_idx = to_device(tok_idx, self.opt.gpuid)

		if self.opt.fix_bert == 1:
			with torch.no_grad():
				last, pooled = self.bert(tok_idx)
		else:
			last, pooled = self.bert(tok_idx)

		last = last + pooled.unsqueeze(1) * self.zero

		# move to the original device
		last = to_device(last, self.opt.gpuid)

		self.shared.bert_enc = last
		
		return last


	def begin_pass(self):
		pass

	def end_pass(self):
		pass


