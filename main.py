from __future__ import print_function
import os
import argparse
from itertools import chain

import torch.nn as nn
import torch.backends.cudnn as cudnn
import torch.optim as optim
import torch.utils.data
import torchvision.datasets as dset
import torchvision.transforms as transforms
import torchvision.utils as vutils
from torch.autograd import Variable

# import logger
import numpy as np
import models as ali

parser = argparse.ArgumentParser()
parser.add_argument('--dataset', default='cifar10', help='cifar10 | svhn')
# parser.add_argument('--dataroot', required=True, help='path to dataset')
parser.add_argument('--workers', type=int, help='number of data loading workers', default=1)
parser.add_argument('--batch-size', type=int, default=128, help='input batch size')
parser.add_argument('--image-size', type=int, default=32, help='the height / width of the input image to network')
parser.add_argument('--nc', type=int, default=3, help='input image channels')
parser.add_argument('--nz', type=int, default=256, help='size of the latent z vector')
parser.add_argument('--epochs', type=int, default=10, help='number of epochs to train for')
parser.add_argument('--lr', type=float, default=1e-4, help='learning rate for optimizer, default=1e-4')
parser.add_argument('--beta1', type=float, default=0.5, help='beta1 for adam. default=0.5')
parser.add_argument('--beta2', type=float, default=0.999, help='beta2 for adam. default=0.999')
parser.add_argument('--leaky', type=float, default=0.01, help='leaky relu slope, default=0.01')
parser.add_argument('--std', type=float, default=0.01, help='standard deviation for weights init, default=0.01')
parser.add_argument('--cuda', action='store_true', help='enables cuda')
parser.add_argument('--ngpu', type=int, default=1, help='number of GPUs to use')
# parser.add_argument('--gpu-id', default='0', type=str, help='id(s) for CUDA_VISIBLE_DEVICES')
parser.add_argument('--netGx', default='', help="path to netGx (to continue training)")
parser.add_argument('--netGz', default='', help="path to netGz (to continue training)")
parser.add_argument('--netDz', default='', help="path to netDz (to continue training)")
parser.add_argument('--netDx', default='', help="path to netDx (to continue training)")
parser.add_argument('--netDxz', default='', help="path to netDxz (to continue training)")
parser.add_argument('--clamp_lower', type=float, default=-0.01)
parser.add_argument('--clamp_upper', type=float, default=0.01)
parser.add_argument('--experiment', default=None, help='Where to store samples and models')
opt = parser.parse_args()
print(opt)

# set the device to use by setting CUDA_VISIBLE_DEVICES env variable in
# order to prevent any memory allocation on unused GPUs
# if opt.ngpu == 1:
#     os.environ['CUDA_VISIBLE_DEVICES'] = opt.gpu_id

if opt.experiment is None:
    opt.experiment = 'samples'
os.system('mkdir {0}'.format(opt.experiment))

# opt.manualSeed = random.randint(1, 10000) # fix seed
opt.seed = 0
print("Random Seed: ", opt.seed)
np.random.seed(opt.seed)
torch.manual_seed(opt.seed)

if opt.cuda:
    cudnn.benchmark = True
    torch.cuda.manual_seed_all(opt.seed)

# create logger
LOG_DIR = '{0}/logger'.format(opt.experiment)

# some hyperparameters we wish to save for this experiment
hyperparameters = dict(regularization=1, n_epochs=opt.epochs)
# options for the remote visualization backend
# visdom_opts = dict(server='http://localhost', port=8097)
# create logger for visdom
# xp = logger.Experiment('xp_name', use_visdom=True, visdom_opts=visdom_opts)
# log the hyperparameters of the experiment
# xp.log_config(hyperparameters)
# create parent metric for training metrics (easier interface)
# train_metrics = xp.ParentWrapper(tag='train', name='parent',
#                                  children=(xp.AvgMetric(name='lossD'),
#                                            xp.AvgMetric(name='lossG')))

if torch.cuda.is_available() and not opt.cuda:
    print("WARNING: You have a CUDA device, so you should probably run with --cuda")

# setup transformations
transforms = transforms.Compose([
    transforms.Scale(opt.image_size),
    transforms.ToTensor(),
    transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5)),
])

if opt.dataset == 'cifar10':
    dataset = dset.CIFAR10(root="../data/", download=True,
                           transform=transforms)
elif opt.dataset == 'svhn':
    dataset = dset.SVHN(root="../data/", download=True,
                        transform=transforms)
dataloader = torch.utils.data.DataLoader(dataset, batch_size=opt.batch_size,
                                         shuffle=True, num_workers=int(opt.workers))

ngpu = int(opt.ngpu)  # number of GPUs
nc = int(opt.nc)  # number input channels
nz = int(opt.nz)  # latent space size

eps = 1e-15  # to avoid possible numerical instabilities during backward

# create models and load parameters if needed
netGx, netGz, netDx, netDz, netDxz = ali.create_models(opt.dataset, nz, ngpu)

if opt.netGz != '':  # load checkpoint if needed
    netGz.load_state_dict(torch.load(opt.netGz))
print(netGz)

if opt.netGx != '':  # load checkpoint if needed
    netGx.load_state_dict(torch.load(opt.netGx))
print(netGx)

if opt.netDz != '':  # load checkpoint if needed
    netDz.load_state_dict(torch.load(opt.netDz))
print(netDz)

if opt.netDx != '':  # load checkpoint if needed
    netDx.load_state_dict(torch.load(opt.netDx))
print(netDx)

if opt.netDxz != '':  # load checkpoint if needed
    netDxz.load_state_dict(torch.load(opt.netDxz))
print(netDxz)

# setup input tensors
x = torch.FloatTensor(opt.batch_size, nc, opt.image_size, opt.image_size)
z = torch.FloatTensor(opt.batch_size, nz, 1, 1)
noise = torch.FloatTensor(opt.batch_size, 1, 1, 1)

if opt.cuda:
    netGx.cuda(), netGz.cuda()
    netDx.cuda(), netDz.cuda(), netDxz.cuda()
    x, z, noise = x.cuda(), z.cuda(), noise.cuda()

x, z, noise = Variable(x), Variable(z), Variable(noise)

# setup optimizer
dis_params = chain(netDx.parameters(), netDz.parameters(), netDxz.parameters())
gen_params = chain(netGx.parameters(), netGz.parameters())

kwargs_adam = {'lr': opt.lr, 'betas': (opt.beta1, opt.beta2)}
optimizerD = optim.Adam(dis_params, **kwargs_adam)
optimizerG = optim.Adam(gen_params, **kwargs_adam)


def softplus(_x):
    return torch.log(1.0 + torch.exp(_x))


def compute_loss(batch_size, d_loss=False):
    z_hat = netGz(x)
    mu, sigma = z_hat[:, :opt.nz], z_hat[:, opt.nz:].exp()

    z_hat = mu + sigma * noise.expand_as(sigma)
    x_hat = netGx(z)

    data_preds = netDxz(torch.cat([netDx(x), netDz(z_hat)], 1)) + eps
    sample_preds = netDxz(torch.cat([netDx(x_hat), netDz(z)], 1)) + eps

    if d_loss:
        # discriminator loss
        loss = torch.mean(softplus(-data_preds) + softplus(sample_preds))
    else:
        # generator loss
        loss = torch.mean(softplus(data_preds) + softplus(-sample_preds))

    return loss


def train(dataloader, epoch):
    # Set the networks in train mode (apply dropout when needed)
    netDx.train(), netDz.train(), netDxz.train()
    netGx.train(), netGz.train()

    for batch_id, (real_cpu, _) in enumerate(dataloader):
        ###########################
        # Prepare data
        ###########################
        batch_size = real_cpu.size(0)
        x.data.resize_(real_cpu.size()).copy_(real_cpu)

        # generate random data
        rndm_args = {'mean': 0, 'std': 1}
        z.data.resize_(batch_size, nz, 1, 1).normal_(**rndm_args)
        noise.data.resize_(batch_size, 1, 1, 1).normal_(**rndm_args)

        # clamp parameters to a cube
        for p in netDx.parameters():
            p.data.clamp_(opt.clamp_lower, opt.clamp_upper)
        for p in netDz.parameters():
            p.data.clamp_(opt.clamp_lower, opt.clamp_upper)
        for p in netDxz.parameters():
            p.data.clamp_(opt.clamp_lower, opt.clamp_upper)
        for p in netGx.parameters():
            p.data.clamp_(opt.clamp_lower, opt.clamp_upper)
        for p in netGz.parameters():
            p.data.clamp_(opt.clamp_lower, opt.clamp_upper)

        # equation (2) from the paper
        # q(z | x) = N(mu(x), sigma^2(x) I)
        '''z_hat = netGz(x)
        mu, sigma = z_hat[:, :opt.nz], z_hat[:, opt.nz:].exp()

        z_hat = mu + sigma * noise.expand_as(sigma)
        x_hat = netGx(z)

        # approach following theano code
        #input_x = torch.cat([x, x_hat], 0)
        #input_z = torch.cat([z_hat, z], 0)

     #   dxz = netDxz(torch.cat([netDx(input_x), netDz(input_z)], 1)) + eps

     #   data_preds = dxz[:x.size(0)]
     #   sample_preds = dxz[x.size(0):]

        data_preds = netDxz(torch.cat([netDx(x), netDz(z_hat)], 1)) +eps
        sample_preds = netDxz(torch.cat([netDx(x_hat), netDz(z)], 1)) +eps

        #netDz.zero_grad(), netDx.zero_grad(), netDxz.zero_grad()


        #D_loss = torch.mean(softplus(-data_preds) + softplus(sample_preds))
        D_loss = torch.mean(nn.Softplus()(-data_preds) + nn.Softplus()(sample_preds))
        optimizerD.zero_grad()
        netDz.zero_grad(), netDx.zero_grad(), netDxz.zero_grad()
        D_loss.backward(retain_variables=True)  # Backpropagate loss
        optimizerD.step()  # Apply optimization step

        #netDz.zero_grad(), netDx.zero_grad(), netDxz.zero_grad()
        #netGx.zero_grad(), netGz.zero_grad()

        #netGx.zero_grad(), netGz.zero_grad()

        G_loss = torch.mean(nn.Softplus()(data_preds) + nn.Softplus()(-sample_preds))
        optimizerG.zero_grad()
        netGx.zero_grad(), netGz.zero_grad()
        G_loss.backward()  # Backpropagate loss
        optimizerG.step()  # Apply optimization step

        #Loss = D_loss + G_loss
        #Loss.backward()

        #optimizerD.step()  # Apply optimization step
        #optimizerG.step()  # Apply optimization step'''

        D_loss = compute_loss(batch_size, d_loss=True)
        G_loss = compute_loss(batch_size, d_loss=False)

        for p in netGx.parameters():
            p.requires_grad = False  # to avoid computation 
        for p in netGz.parameters():
            p.requires_grad = False  # to avoid computation
        for p in netDx.parameters():
            p.requires_grad = True  # to avoid computation
        for p in netDz.parameters():
            p.requires_grad = True  # to avoid computation
        for p in netDxz.parameters():
            p.requires_grad = True  # to avoid computation

        optimizerD.zero_grad()
        D_loss.backward()
        optimizerD.step()  # Apply optimization step

        for p in netGx.parameters():
            p.requires_grad = True  # to avoid computation
        for p in netGz.parameters():
            p.requires_grad = True  # to avoid computation
        for p in netDx.parameters():
            p.requires_grad = False  # to avoid computation
        for p in netDz.parameters():
            p.requires_grad = False  # to avoid computation
        for p in netDxz.parameters():
            p.requires_grad = False  # to avoid computation

        optimizerG.zero_grad()
        G_loss.backward()
        optimizerG.step()  # Apply optimization step

        ############################
        # Logging stuff
        ###########################

        print('[{}/{}][{}/{}] Loss_D: {} Loss_G: {}'
              .format(epoch+1, opt.epochs, batch_id+1, len(dataloader),
                      D_loss.data[0], G_loss.data[0]))

        # TODO(edgarriba): fixme since raises cuda out of memory
        # train_metrics.update(lossD=D_loss.data.cpu().numpy()[0],
        #                      lossG=G_loss.data.cpu().numpy()[0],
        #                      n=len(real_cpu))

    # Method 2 for logging: log Parent wrapper
    # (automatically logs all children)
    # xp.log_metric(train_metrics)


def test(dataloader, epoch):
    real_cpu_first, _ = iter(dataloader).next()
    real_cpu_first = real_cpu_first.mul(0.5).add(0.5)  # denormalize

    if opt.cuda:
        real_cpu_first = real_cpu_first.cuda()

    netGx.eval(), netGz.eval()  # switch to test mode
    latent = netGz(Variable(real_cpu_first, volatile=True))

    # removes last sigmoid activation to visualize reconstruction correctly
    mu, sigma = latent[:, :opt.nz], latent[:, opt.nz:].exp()
    recon = netGx(mu + sigma)

    vutils.save_image(recon.data, '{0}/reconstruction.png'.format(opt.experiment))
    vutils.save_image(real_cpu_first, '{0}/real_samples.png'.format(opt.experiment))


# MAIN LOOP

for epoch in range(opt.epochs):
    # reset training metrics
    # train_metrics.reset()

    # call train/test routines
    train(dataloader, epoch)
    test(dataloader, epoch)

    # do checkpointing
    torch.save(netGx.state_dict(),
               '{0}/netGx_epoch_{1}.pth'.format(opt.experiment, epoch))
    torch.save(netGz.state_dict(),
               '{0}/netGz_epoch_{1}.pth'.format(opt.experiment, epoch))
    torch.save(netDx.state_dict(),
               '{0}/netDx_epoch_{1}.pth'.format(opt.experiment, epoch))
    torch.save(netDz.state_dict(),
               '{0}/netDz_epoch_{1}.pth'.format(opt.experiment, epoch))
    torch.save(netDxz.state_dict(),
               '{0}/netDxz_epoch_{1}.pth'.format(opt.experiment, epoch))
