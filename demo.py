import sys
from pipeline import *
import argparse
import h5py
import numpy as np
import torch
from torch import nn
from torch import cuda
from holder import *
from util import *
import spacy
from preprocess import pad

spacy_nlp = spacy.load('en')


parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.ArgumentDefaultsHelpFormatter)

parser.add_argument('--load_file', help="The path to pretrained model (optional)", default = "")
parser.add_argument('--label_dict', help="The path to label dictionary", default = "./data/srl/conll2012.label.dict")
## pipeline specs
parser.add_argument('--max_num_subtok', help="Maximal number subtokens in a word", type=int, default=8)
parser.add_argument('--hidden_size', help="The general hidden size of the pipeline", type=int, default=768)
parser.add_argument('--num_label', help="The number of label", type=int, default=129)
parser.add_argument('--max_seq_l', help="Maximal sequence length", type=int, default=200)
# bert specs
parser.add_argument('--bert_type', help="The type of bert encoder from huggingface, eg. roberta-base",default = "roberta-base")
parser.add_argument('--bert_size', help="The input bert dim", type=int, default=768)
parser.add_argument('--compact_mode', help="How word pieces be mapped to word level label", default='whole_word')
## pipeline stages
parser.add_argument('--enc', help="The type of encoder, e.g., bert", default='bert')
parser.add_argument('--cls', help="The type of classifier, e.g., linear", default='linear')
#
parser.add_argument('--gpuid', help="The GPU index, if -1 then use CPU", type=int, default=-1)
parser.add_argument('--verbose', help="Whether to print out every prediction", type=int, default=0)
parser.add_argument('--num_frame', help="The number of frame for each proposition", type=int, default=38)


def process(opt, tokenizer, seq):
	bos_tok, eos_tok = get_special_tokens(tokenizer)
	ws = spacy_nlp(seq)
	sent_subtoks = [tokenizer.tokenize(t.text) for t in ws]
	tok_l = [len(subtoks) for subtoks in sent_subtoks]
	toks = [p for subtoks in sent_subtoks for p in subtoks]	# flatterning
	orig_toks = [t.text for t in ws]

	# pad for CLS and SEP
	CLS, SEP = tokenizer.cls_token, tokenizer.sep_token
	toks = [CLS] + toks + [SEP]
	tok_l = [1] + tok_l + [1]
	orig_toks = [CLS] + orig_toks + [SEP]

	tok_idx = np.array(tokenizer.convert_tokens_to_ids(toks), dtype=int)

	# note that the resulted actual seq length after subtoken collapsing could be different even within the same batch
	#	actual seq length is the origial sequence length
	#	seq length is the length after subword tokenization
	acc = 0
	sub2tok_idx = []
	for l in tok_l:
		sub2tok_idx.append(pad([p for p in range(acc, acc+l)], opt.max_num_subtok, -1))
		assert(len(sub2tok_idx[-1]) <= opt.max_num_subtok)
		acc += l
	#sub2tok_idx = pad(sub2tok_idx, opt.max_seq_l, [-1 for _ in range(opt.max_num_subtok)])
	sub2tok_idx = np.array(sub2tok_idx, dtype=int)

	return tok_idx, sub2tok_idx, toks, orig_toks


def fix_opt(opt):
	opt.loss = 'crf'
	opt.use_gold_predicate = 0
	opt.fix_bert = 0
	opt.dropout = 0
	opt.lambd = "1.0"
	opt.param_init_type = 'xavier_uniform'
	return opt

def pretty_print_pred(opt, shared, m, pred_idx):
	batch_l = shared.batch_l
	orig_l = shared.orig_seq_l
	bv_idx = int(np.where(m.loss[0].labels == 'B-V')[0][0])

	pred_log =[]
	for i in range(batch_l):
		orig_l_i = orig_l[i].item()	# convert to scalar
		a_pred_i = pred_idx[i, :orig_l_i, :orig_l_i]

		orig_tok_grouped = shared.res_map['orig_tok_grouped'][i][1:-1]
		pred_log.append(m.loss[0].compose_log(orig_tok_grouped, a_pred_i[1:-1, 1:-1].cpu(), transpose=False))
	return pred_log


def run(opt, shared, m, tokenizer, seq):
	tok_idx, sub2tok_idx, toks, orig_toks = process(opt, tokenizer, seq)

	m.update_context([0], 1, torch.tensor([len(tok_idx)]).int(), torch.tensor([len(orig_toks)]).int(), torch.tensor([sub2tok_idx]).int(), {'orig_tok_grouped': [orig_toks]})

	tok_idx = Variable(torch.tensor([tok_idx]), requires_grad=False)

	with torch.no_grad():
		_, pred_idx = m.forward(tok_idx, skip_loss_forward=True)

	log = pretty_print_pred(opt, shared, m, pred_idx)[0]
	return orig_toks[1:-1], log


def init(args):
	opt = parser.parse_args(args)
	opt = fix_opt(opt)
	shared = Holder()

	if opt.gpuid != -1:
		torch.cuda.set_device(opt.gpuid)

	# build model
	m = Pipeline(opt, shared)

	# initializing from pretrained
	print('loading pretrained model from {0}...'.format(opt.load_file))
	param_dict = load_param_dict('{0}.hdf5'.format(opt.load_file))
	m.set_param_dict(param_dict, verbose=False)

	if opt.gpuid != -1:
		m.distribute()	# distribute to multigpu

	tokenizer = AutoTokenizer.from_pretrained(opt.bert_type)

	return opt, shared, m, tokenizer


def main(args):
	opt, shared, m, tokenizer = init(args)

	while True:
		try:
			seq = input("Enter a sequence: ")
			orig_toks, log = run(opt, shared, m, tokenizer, seq)
			print('***********************************')
			print(' '.join(orig_toks))
			print(log)

		except KeyboardInterrupt:
			return
		except BaseException as e:
			print(e.with_traceback)


if __name__ == '__main__':
	sys.exit(main(sys.argv[1:]))

