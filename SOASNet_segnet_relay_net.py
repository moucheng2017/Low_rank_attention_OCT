import torch
import math
import numpy as np
import torch.nn as nn
import torch.nn.functional as F

from NNBaselines import segnet_encoder, segnet_decoder, unpool_layer


def double_conv(in_channels, out_channels, kernel_1, kernel_2, step_1, step_2, norm):
    # ===================
    if norm == 'in':
        return nn.Sequential(
            nn.Conv2d(in_channels, out_channels, 3, stride=1, padding=1, groups=1, bias=False),
            nn.InstanceNorm2d(out_channels, affine=True),
            nn.ReLU(inplace=True),
            nn.Conv2d(out_channels, out_channels, kernel_size=(kernel_1, kernel_2), stride=(step_1, step_2), padding=1, groups=1, bias=False),
            nn.InstanceNorm2d(out_channels, affine=True),
            nn.ReLU(inplace=True)
        )
    elif norm == 'bn':
        return nn.Sequential(
            nn.Conv2d(in_channels, out_channels, 3, stride=1, padding=1, groups=1, bias=False),
            nn.BatchNorm2d(out_channels, affine=True),
            nn.ReLU(inplace=True),
            nn.Conv2d(out_channels, out_channels, kernel_size=(kernel_1, kernel_2), stride=(step_1, step_2), padding=1, groups=1, bias=False),
            nn.BatchNorm2d(out_channels, affine=True),
            nn.ReLU(inplace=True)
        )
    elif norm == 'ln':
        return nn.Sequential(
            nn.Conv2d(in_channels, out_channels, 3, stride=1, padding=1, groups=1, bias=False),
            nn.GroupNorm(out_channels, out_channels, affine=True),
            nn.ReLU(inplace=True),
            nn.Conv2d(out_channels, out_channels, kernel_size=(kernel_1, kernel_2), stride=(step_1, step_2), padding=1, groups=1, bias=False),
            nn.GroupNorm(out_channels, out_channels, affine=True),
            nn.ReLU(inplace=True)
        )
    elif norm == 'gn':
        return nn.Sequential(
            nn.Conv2d(in_channels, out_channels, 3, stride=1, padding=1, groups=1, bias=False),
            nn.GroupNorm(out_channels // 8, out_channels, affine=True),
            nn.ReLU(inplace=True),
            nn.Conv2d(out_channels, out_channels, kernel_size=(kernel_1, kernel_2), stride=(step_1, step_2), padding=1, groups=1, bias=False),
            nn.GroupNorm(out_channels // 8, out_channels, affine=True),
            nn.ReLU(inplace=True)
        )


def conv_block(in_channels, out_channels, kernel_h, kernel_w, step_h, step_w, padding_h, padding_w, norm, group):
    # ===================
    if norm == 'in':
        return nn.Sequential(
            nn.Conv2d(in_channels, out_channels, kernel_size=(kernel_h, kernel_w), stride=(step_h, step_w), padding=(padding_h, padding_w), groups=group, bias=False),
            nn.InstanceNorm2d(out_channels, affine=True),
            nn.ReLU(inplace=True)
        )
    elif norm == 'bn':
        return nn.Sequential(
            nn.Conv2d(in_channels, out_channels, kernel_size=(kernel_h, kernel_w), stride=(step_h, step_w), padding=(padding_h, padding_w), groups=group, bias=False),
            nn.BatchNorm2d(out_channels, affine=True),
            nn.ReLU(inplace=True)
        )
    elif norm == 'ln':
        return nn.Sequential(
            nn.Conv2d(in_channels, out_channels, kernel_size=(kernel_h, kernel_w), stride=(step_h, step_w), padding=(padding_h, padding_w), groups=group, bias=False),
            nn.GroupNorm(out_channels, out_channels, affine=True),
            nn.ReLU(inplace=True)
        )
    elif norm == 'gn':
        return nn.Sequential(
            nn.Conv2d(in_channels, out_channels, kernel_size=(kernel_h, kernel_w), stride=(step_h, step_w), padding=(padding_h, padding_w), groups=group, bias=False),
            nn.GroupNorm(out_channels // 8, out_channels, affine=True),
            nn.ReLU(inplace=True)
        )


class SOASNet_segnet_skip(nn.Module):
    #
    def __init__(self, in_ch, width, depth, norm, n_classes, side_output=False, downsampling_limit=5, mode='relaynet'):
        # =================================================================================================================
        # mode == 'low_rank_attn': our model
        # mode == 'unet': standard u-net
        # depth-wise mixed attention
        # ==============================
        super(SOASNet_segnet_skip, self).__init__()

        self.side_output_mode = side_output
        self.depth = depth
        self.mode = mode
        self.downsampling_stages_limit = downsampling_limit

        if n_classes == 2:

            output_channel = 1

        else:

            output_channel = n_classes

        # Isotropic path:
        self.first_layer = conv_block(in_channels=in_ch, out_channels=width // 2, kernel_h=5, kernel_w=5, step_h=1, step_w=1, padding_h=2, padding_w=2, norm=norm, group=1)

        self.encoders = nn.ModuleList()

        self.decoders_unpooling = nn.ModuleList()
        self.decoders = nn.ModuleList()

        self.encoders_output_channels = []

        if self.mode == 'low_rank_attn':

            encoders_output_channels_side = 0

            self.encoders_side_output_channels = []
            # Width path:
            self.width_encoders_group_1 = nn.ModuleList()

            self.width_encoders_group_2 = nn.ModuleList()

            self.width_encoders_group_3 = nn.ModuleList()

            self.width_encoders_group_4 = nn.ModuleList()

            self.width_decoders_group_1 = nn.ModuleList()

            self.width_decoders_group_2 = nn.ModuleList()

            self.width_decoders_group_3 = nn.ModuleList()

            self.width_decoders_group_4 = nn.ModuleList()

            self.encoders_bottlenecks = nn.ModuleList()
            # Height path:
            self.height_encoders_group_1 = nn.ModuleList()

            self.height_encoders_group_2 = nn.ModuleList()

            self.height_encoders_group_3 = nn.ModuleList()

            self.height_encoders_group_4 = nn.ModuleList()

            self.height_decoders_group_1 = nn.ModuleList()

            self.height_decoders_group_2 = nn.ModuleList()

            self.height_decoders_group_3 = nn.ModuleList()

            self.height_decoders_group_4 = nn.ModuleList()

            self.decoders_bottlenecks = nn.ModuleList()

        elif self.mode == 'single_dim_net':

            self.encoders_horinzontal = nn.ModuleList()

            self.encoders_horinzontal_downsample = nn.ModuleList()

        # For encoders:
        for i in range(self.depth + 1):

            if i == 0:

                # self.encoders.append(double_conv(in_channels=width // 2, out_channels=width, kernel_1=3, kernel_2=3, step_1=2, step_2=2, norm=norm))

                self.encoders.append(segnet_encoder(in_channels=width // 2, out_channels=width, mode=norm))

                self.encoders_output_channels.append(width)

                if self.mode == 'single_dim_net':

                    for j in range(self.depth - i):

                        self.encoders_horinzontal.append(double_conv(in_channels=width, out_channels=width, kernel_1=3, kernel_2=3, step_1=1, step_2=1, norm=norm))

                        self.encoders_horinzontal_downsample.append(conv_block(in_channels=width, out_channels=width, kernel_h=2, kernel_w=1, step_h=2, step_w=1, padding_w=0, padding_h=0, norm=norm, group=1))

                if self.mode == 'low_rank_attn':

                    encoders_output_channels_side = width // 2

                    # self.width_encoders_first_group_1 = conv_block(in_channels=width // 2, out_channels=width // 2, kernel_h=1, kernel_w=2, step_h=1, step_w=2, padding_w=0, padding_h=0, norm=norm, group=width // 16)
                    #
                    # self.height_encoders_first_group_1 = conv_block(in_channels=width // 2, out_channels=width // 2, kernel_h=2, kernel_w=1, step_h=2, step_w=1, padding_w=0, padding_h=0, norm=norm, group=width // 16)
                    #
                    # self.width_encoders_first_group_2 = conv_block(in_channels=width // 2, out_channels=width // 2, kernel_h=1, kernel_w=3, step_h=1, step_w=2, padding_w=1, padding_h=0, norm=norm, group=width // 8)
                    #
                    # self.height_encoders_first_group_2 = conv_block(in_channels=width // 2, out_channels=width // 2, kernel_h=3, kernel_w=1, step_h=2, step_w=1, padding_w=0, padding_h=1, norm=norm, group=width // 8)
                    #
                    # self.width_encoders_first_group_3 = conv_block(in_channels=width // 2, out_channels=width // 2, kernel_h=1, kernel_w=5, step_h=1, step_w=2, padding_w=2, padding_h=0, norm=norm, group=width // 4)
                    #
                    # self.height_encoders_first_group_3 = conv_block(in_channels=width // 2, out_channels=width // 2, kernel_h=5, kernel_w=1, step_h=2, step_w=1, padding_w=0, padding_h=2, norm=norm, group=width // 4)
                    #
                    # self.width_encoders_first_group_4 = conv_block(in_channels=width // 2, out_channels=width // 2, kernel_h=1, kernel_w=7, step_h=1, step_w=2, padding_w=3, padding_h=0, norm=norm, group=width // 2)
                    #
                    # self.height_encoders_first_group_4 = conv_block(in_channels=width // 2, out_channels=width // 2, kernel_h=7, kernel_w=1, step_h=2, step_w=1, padding_w=0, padding_h=3, norm=norm, group=width // 2)

                    self.width_encoders_first_group_1 = nn.Conv2d(in_channels=width // 2, out_channels=width // 2, kernel_size=(1, 2), stride=(1, 2), padding=(0, 0), groups=width // 16, bias=False)

                    self.height_encoders_first_group_1 = nn.Conv2d(in_channels=width // 2, out_channels=width // 2, kernel_size=(2, 1), stride=(2, 1), padding=(0, 0), groups=width // 16, bias=False)

                    self.width_encoders_first_group_2 = nn.Conv2d(in_channels=width // 2, out_channels=width // 2, kernel_size=(1, 3), stride=(1, 2), padding=(0, 1), groups=width // 8, bias=False)

                    self.height_encoders_first_group_2 = nn.Conv2d(in_channels=width // 2, out_channels=width // 2, kernel_size=(3, 1), stride=(2, 1), padding=(1, 0), groups=width // 8, bias=False)

                    self.width_encoders_first_group_3 = nn.Conv2d(in_channels=width // 2, out_channels=width // 2, kernel_size=(1, 5), stride=(1, 2), padding=(0, 2), groups=width // 4, bias=False)

                    self.height_encoders_first_group_3 = nn.Conv2d(in_channels=width // 2, out_channels=width // 2, kernel_size=(5, 1), stride=(2, 1), padding=(2, 0), groups=width // 4, bias=False)

                    self.width_encoders_first_group_4 = nn.Conv2d(in_channels=width // 2, out_channels=width // 2, kernel_size=(1, 7), stride=(1, 2), padding=(0, 3), groups=width // 2, bias=False)

                    self.height_encoders_first_group_4 = nn.Conv2d(in_channels=width // 2, out_channels=width // 2, kernel_size=(7, 1), stride=(2, 1), padding=(3, 0), groups=width // 2, bias=False)

                    self.encoders_bottlenecks.append(nn.Conv2d(in_channels=width // 2, out_channels=width // 2, kernel_size=1, stride=1, padding=0, bias=True))

                    self.encoders_side_output_channels.append(encoders_output_channels_side)

            elif i < self.downsampling_stages_limit + 1:

                # self.encoders.append(double_conv(in_channels=width*(2**(i-1)), out_channels=width*(2**i), kernel_1=3, kernel_2=3, step_1=2, step_2=2, norm=norm))

                self.encoders.append(segnet_encoder(in_channels=width*(2**(i-1)), out_channels=width*(2**i), mode=norm))

                self.encoders_output_channels.append(width*(2**i))

                if self.mode == 'single_dim_net':

                    for j in range(self.depth - i):

                        self.encoders_horinzontal.append(double_conv(in_channels=width*(2**i), out_channels=width*(2**i), kernel_1=3, kernel_2=3, step_1=1, step_2=1, norm=norm))

                        self.encoders_horinzontal_downsample.append(conv_block(in_channels=width*(2**i), out_channels=width*(2**i), kernel_h=2, kernel_w=1, step_h=2, step_w=1, padding_w=0, padding_h=0, norm=norm, group=1))

                if self.mode == 'low_rank_attn':

                    encoders_output_channels_side = width // 2

                    self.encoders_bottlenecks.append(nn.Conv2d(in_channels=width // 2, out_channels=width // 2, kernel_size=1, stride=1, padding=0, bias=True))

                    self.encoders_side_output_channels.append(encoders_output_channels_side)

            else:

                # self.encoders.append(double_conv(in_channels=width*2**self.downsampling_stages_limit, out_channels=width*2**self.downsampling_stages_limit, kernel_1=3, kernel_2=3, step_1=2, step_2=2, norm=norm))

                self.encoders.append(segnet_encoder(in_channels=width*2**self.downsampling_stages_limit, out_channels=width*2**self.downsampling_stages_limit, mode=norm))

                self.encoders_output_channels.append(width*2**self.downsampling_stages_limit)

                if self.mode == 'single_dim_net':

                    for j in range(self.depth - i):

                        self.encoders_horinzontal.append(double_conv(in_channels=width*2**self.downsampling_stages_limit, out_channels=width*2**self.downsampling_stages_limit, kernel_1=3, kernel_2=3, step_1=1, step_2=1, norm=norm))

                        self.encoders_horinzontal_downsample.append(conv_block(in_channels=width*2**self.downsampling_stages_limit, out_channels=width*2**self.downsampling_stages_limit, kernel_h=2, kernel_w=1, step_h=2, step_w=1, padding_w=0, padding_h=0, norm=norm, group=1))

                if self.mode == 'low_rank_attn':

                    self.encoders_bottlenecks.append(nn.Conv2d(in_channels=encoders_output_channels_side, out_channels=encoders_output_channels_side // 2, kernel_size=1, stride=1, padding=0, bias=True))

                    encoders_output_channels_side = encoders_output_channels_side // 2

                    # self.width_encoders_group_1.append(conv_block(in_channels=encoders_output_channels_side, out_channels=encoders_output_channels_side, kernel_h=1, kernel_w=2, step_h=1, step_w=2, padding_w=0, padding_h=0, norm=norm, group=encoders_output_channels_side // 8))
                    #
                    # self.width_encoders_group_2.append(conv_block(in_channels=encoders_output_channels_side, out_channels=encoders_output_channels_side, kernel_h=1, kernel_w=3, step_h=1, step_w=2, padding_w=1, padding_h=0, norm=norm, group=encoders_output_channels_side // 4))
                    #
                    # self.width_encoders_group_3.append(conv_block(in_channels=encoders_output_channels_side, out_channels=encoders_output_channels_side, kernel_h=1, kernel_w=5, step_h=1, step_w=2, padding_w=2, padding_h=0, norm=norm, group=encoders_output_channels_side // 2))
                    #
                    # self.width_encoders_group_4.append(conv_block(in_channels=encoders_output_channels_side, out_channels=encoders_output_channels_side, kernel_h=1, kernel_w=7, step_h=1, step_w=2, padding_w=3, padding_h=0, norm=norm, group=encoders_output_channels_side))
                    #
                    # self.height_encoders_group_1.append(conv_block(in_channels=encoders_output_channels_side, out_channels=encoders_output_channels_side, kernel_h=2, kernel_w=1, step_h=2, step_w=1, padding_w=0, padding_h=0, norm=norm, group=encoders_output_channels_side // 8))
                    #
                    # self.height_encoders_group_2.append(conv_block(in_channels=encoders_output_channels_side, out_channels=encoders_output_channels_side, kernel_h=3, kernel_w=1, step_h=2, step_w=1, padding_w=0, padding_h=1, norm=norm, group=encoders_output_channels_side // 4))
                    #
                    # self.height_encoders_group_3.append(conv_block(in_channels=encoders_output_channels_side, out_channels=encoders_output_channels_side, kernel_h=5, kernel_w=1, step_h=2, step_w=1, padding_w=0, padding_h=2, norm=norm, group=encoders_output_channels_side // 2))
                    #
                    # self.height_encoders_group_4.append(conv_block(in_channels=encoders_output_channels_side, out_channels=encoders_output_channels_side, kernel_h=7, kernel_w=1, step_h=2, step_w=1, padding_w=0, padding_h=3, norm=norm, group=encoders_output_channels_side))

                    self.width_encoders_group_1.append(nn.Conv2d(in_channels=encoders_output_channels_side, out_channels=encoders_output_channels_side, kernel_size=(1, 2), stride=(1, 2), padding=(0, 0), groups=encoders_output_channels_side // 8, bias=False))

                    self.width_encoders_group_2.append(nn.Conv2d(in_channels=encoders_output_channels_side, out_channels=encoders_output_channels_side, kernel_size=(1, 3), stride=(1, 2), padding=(0, 1), groups=encoders_output_channels_side // 4, bias=False))

                    self.width_encoders_group_3.append(nn.Conv2d(in_channels=encoders_output_channels_side, out_channels=encoders_output_channels_side, kernel_size=(1, 5), stride=(1, 2), padding=(0, 2), groups=encoders_output_channels_side // 2, bias=False))

                    self.width_encoders_group_4.append(nn.Conv2d(in_channels=encoders_output_channels_side, out_channels=encoders_output_channels_side, kernel_size=(1, 7), stride=(1, 2), padding=(0, 3), groups=encoders_output_channels_side, bias=False))

                    self.height_encoders_group_1.append(nn.Conv2d(in_channels=encoders_output_channels_side, out_channels=encoders_output_channels_side, kernel_size=(2, 1), stride=(2, 1), padding=(0, 0), groups=encoders_output_channels_side // 8, bias=False))

                    self.height_encoders_group_2.append(nn.Conv2d(in_channels=encoders_output_channels_side, out_channels=encoders_output_channels_side, kernel_size=(3, 1), stride=(2, 1), padding=(1, 0), groups=encoders_output_channels_side // 4, bias=False))

                    self.height_encoders_group_3.append(nn.Conv2d(in_channels=encoders_output_channels_side, out_channels=encoders_output_channels_side, kernel_size=(5, 1), stride=(2, 1), padding=(2, 0), groups=encoders_output_channels_side // 2, bias=False))

                    self.heights_encoders_group_4.append(nn.Conv2d(in_channels=encoders_output_channels_side, out_channels=encoders_output_channels_side, kernel_size=(7, 1), stride=(2, 1), padding=(3, 0), groups=encoders_output_channels_side, bias=False))

                    self.encoders_side_output_channels.append(encoders_output_channels_side)

        # ==============================================================================
        # ==============================================================================
        # Decoders
        # ==============================================================================
        # ==============================================================================

        for i in range(self.depth):

            if self.mode == 'single_dim_net':

                self.decoders.append(conv_block(in_channels=self.encoders_output_channels[-i - 1], out_channels=self.encoders_output_channels[-i - 1], kernel_h=2, kernel_w=1, step_h=2, step_w=1, padding_w=0, padding_h=0, norm=norm, group=1))

                self.decoders.append(conv_block(in_channels=self.encoders_output_channels[-i - 1] + self.encoders_output_channels[-i - 2], out_channels=self.encoders_output_channels[-i - 2], kernel_h=3, kernel_w=3, step_h=1, step_w=1, padding_w=1, padding_h=1, norm=norm, group=1))

            else:

                self.decoders.append(double_conv(in_channels=self.encoders_output_channels[-i - 1] + self.encoders_output_channels[-i - 2], out_channels=self.encoders_output_channels[-i - 2], kernel_1=3, kernel_2=3, step_1=1, step_2=1, norm=norm))

                self.decoders_unpooling.append(unpool_layer())

            if self.mode == 'low_rank_attn':

                # self.width_decoders_group_1.append(conv_block(in_channels=self.encoders_side_output_channels[- (i + 1)], out_channels=self.encoders_side_output_channels[- (i + 2)], kernel_h=2, kernel_w=1, step_h=2, step_w=1, padding_w=0, padding_h=0, norm=norm, group=self.encoders_side_output_channels[- (i + 2)] // 8))

                # self.width_decoders_group_2.append(conv_block(in_channels=self.encoders_side_output_channels[- (i + 1)], out_channels=self.encoders_side_output_channels[- (i + 2)], kernel_h=3, kernel_w=1, step_h=2, step_w=1, padding_w=0, padding_h=1, norm=norm, group=self.encoders_side_output_channels[- (i + 2)] // 4))

                # self.width_decoders_group_3.append(conv_block(in_channels=self.encoders_side_output_channels[- (i + 1)], out_channels=self.encoders_side_output_channels[- (i + 2)], kernel_h=5, kernel_w=1, step_h=2, step_w=1, padding_w=0, padding_h=2, norm=norm, group=self.encoders_side_output_channels[- (i + 2)] // 2))

                # self.width_decoders_group_4.append(conv_block(in_channels=self.encoders_side_output_channels[- (i + 1)], out_channels=self.encoders_side_output_channels[- (i + 2)], kernel_h=7, kernel_w=1, step_h=2, step_w=1, padding_w=0, padding_h=3, norm=norm, group=self.encoders_side_output_channels[- (i + 2)]))

                # self.height_decoders_group_1.append(conv_block(in_channels=self.encoders_side_output_channels[- (i + 1)], out_channels=self.encoders_side_output_channels[- (i + 2)], kernel_h=1, kernel_w=2, step_h=1, step_w=2, padding_w=0, padding_h=0, norm=norm, group=self.encoders_side_output_channels[- (i + 2)] // 8))

                # self.height_decoders_group_2.append(conv_block(in_channels=self.encoders_side_output_channels[- (i + 1)], out_channels=self.encoders_side_output_channels[- (i + 2)], kernel_h=1, kernel_w=3, step_h=1, step_w=2, padding_w=1, padding_h=0, norm=norm, group=self.encoders_side_output_channels[- (i + 2)] // 4))

                # self.height_decoders_group_3.append(conv_block(in_channels=self.encoders_side_output_channels[- (i + 1)], out_channels=self.encoders_side_output_channels[- (i + 2)], kernel_h=1, kernel_w=5, step_h=1, step_w=2, padding_w=2, padding_h=0, norm=norm, group=self.encoders_side_output_channels[- (i + 2)] // 2))

                # self.height_decoders_group_4.append(conv_block(in_channels=self.encoders_side_output_channels[- (i + 1)], out_channels=self.encoders_side_output_channels[- (i + 2)], kernel_h=1, kernel_w=7, step_h=1, step_w=2, padding_w=3, padding_h=0, norm=norm, group=self.encoders_side_output_channels[- (i + 2)]))

                self.width_decoders_group_1.append(nn.Conv2d(in_channels=self.encoders_side_output_channels[- (i + 1)], out_channels=self.encoders_side_output_channels[- (i + 2)], kernel_size=(2, 1), stride=(2, 1), padding=(0, 0), groups=self.encoders_side_output_channels[- (i + 2)] // 8, bias=False))

                self.width_decoders_group_2.append(nn.Conv2d(in_channels=self.encoders_side_output_channels[- (i + 1)], out_channels=self.encoders_side_output_channels[- (i + 2)], kernel_size=(3, 1), stride=(2, 1), padding=(1, 0), groups=self.encoders_side_output_channels[- (i + 2)] // 4, bias=False))

                self.width_decoders_group_3.append(nn.Conv2d(in_channels=self.encoders_side_output_channels[- (i + 1)], out_channels=self.encoders_side_output_channels[- (i + 2)], kernel_size=(5, 1), stride=(2, 1), padding=(2, 0), groups=self.encoders_side_output_channels[- (i + 2)] // 2, bias=False))

                self.width_decoders_group_4.append(nn.Conv2d(in_channels=self.encoders_side_output_channels[- (i + 1)], out_channels=self.encoders_side_output_channels[- (i + 2)], kernel_size=(7, 1), stride=(2, 1), padding=(3, 0), groups=self.encoders_side_output_channels[- (i + 2)], bias=False))

                self.height_decoders_group_1.append(nn.Conv2d(in_channels=self.encoders_side_output_channels[- (i + 1)], out_channels=self.encoders_side_output_channels[- (i + 2)], kernel_size=(1, 2), stride=(1, 2), padding=(0, 0), groups=self.encoders_side_output_channels[- (i + 2)] // 8, bias=False))

                self.height_decoders_group_2.append(nn.Conv2d(in_channels=self.encoders_side_output_channels[- (i + 1)], out_channels=self.encoders_side_output_channels[- (i + 2)], kernel_size=(1, 3), stride=(1, 2), padding=(0, 1), groups=self.encoders_side_output_channels[- (i + 2)] // 4, bias=False))

                self.height_decoders_group_3.append(nn.Conv2d(in_channels=self.encoders_side_output_channels[- (i + 1)], out_channels=self.encoders_side_output_channels[- (i + 2)], kernel_size=(1, 5), stride=(1, 2), padding=(0, 2), groups=self.encoders_side_output_channels[- (i + 2)] // 2, bias=False))

                self.height_decoders_group_4.append(nn.Conv2d(in_channels=self.encoders_side_output_channels[- (i + 1)], out_channels=self.encoders_side_output_channels[- (i + 2)], kernel_size=(1, 7), stride=(1, 2), padding=(0, 3), groups=self.encoders_side_output_channels[- (i + 2)], bias=False))

        self.upsample = nn.Upsample(scale_factor=2, mode='bilinear', align_corners=True)

        if self.mode == 'low_rank_attn':

            if self.depth > self.downsampling_stages_limit:

                self.bridge = double_conv(in_channels=width*2**self.downsampling_stages_limit, out_channels=width*2**self.downsampling_stages_limit, kernel_1=3, kernel_2=3, step_1=1, step_2=1, norm=norm)

            else:

                self.bridge = double_conv(in_channels=self.encoders_output_channels[-1], out_channels=self.encoders_output_channels[-1], kernel_1=3, kernel_2=3, step_1=1, step_2=1, norm=norm)

        self.decoder_last_conv = conv_block(in_channels=width // 2 + width, out_channels=width, kernel_h=3, kernel_w=3, step_h=1, step_w=1, padding_w=1, padding_h=1, norm=norm, group=1)

        self.classification_layer = nn.Conv2d(width, output_channel, kernel_size=1, stride=1, padding=0, bias=True)

    def forward(self, x):

        x_ = self.first_layer(x)

        x_main = x_

        encoder_features = []
        encoder_indices = []
        encoder_pool_shapes = []

        if self.mode == 'low_rank_attn':

            x_height = x_

            x_width = x_

            encoder_height_features = []

            encoder_width_features = []

            if self.side_output_mode is True:

                side_outputs = []

        for i in range(self.depth + 1):

            x_main, indice, shape = self.encoders[i](x_main)
            encoder_indices.append(indice)
            encoder_pool_shapes.append(shape)

            if self.mode == 'low_rank_attn':

                if i > self.downsampling_stages_limit:
                    #
                    x_height = self.encoders_bottlenecks[i](x_height)
                    #
                    x_height_1 = self.height_encoders_group_1[i - self.downsampling_stages_limit - 1](x_height)
                    #
                    # print(x_height_1.shape)
                    #
                    x_height_2 = self.height_encoders_group_2[i - self.downsampling_stages_limit - 1](x_height)
                    #
                    # print(x_height_2.shape)
                    #
                    x_height_3 = self.height_encoders_group_3[i - self.downsampling_stages_limit - 1](x_height)
                    #
                    # print(x_height_3.shape)
                    #
                    x_height_4 = self.height_encoders_group_4[i - self.downsampling_stages_limit - 1](x_height)
                    #
                    # print(x_height_4.shape)
                    #
                    x_height = x_height_1 + x_height_2 + x_height_3 + x_height_4
                    #
                    # diffY = torch.tensor([x_height_1.size()[2] - x_height_2.size()[2]])
                    # diffX = torch.tensor([y_e.size()[3] - y.size()[3]])
                    #
                    x_width = self.encoders_bottlenecks[i](x_width)
                    #
                    x_width_1 = self.width_encoders_group_1[i - self.downsampling_stages_limit - 1](x_width)
                    #
                    # print(x_width_1.shape)
                    #
                    x_width_2 = self.width_encoders_group_2[i - self.downsampling_stages_limit - 1](x_width)
                    #
                    # print(x_width_2.shape)
                    #
                    x_width_3 = self.width_encoders_group_3[i - self.downsampling_stages_limit - 1](x_width)
                    #
                    # print(x_width_3.shape)
                    #
                    x_width_4 = self.width_encoders_group_4[i - self.downsampling_stages_limit - 1](x_width)
                    #
                    # print(x_width_4.shape)
                    #
                    x_width = x_width_1 + x_width_2 + x_width_3 + x_width_4
                    #
                    #
                else:
                    #
                    x_height = self.encoders_bottlenecks[i](x_height)
                    #
                    x_height_1 = self.height_encoders_first_group_1(x_height)
                    #
                    # print(x_height_1.shape)
                    #
                    x_height_2 = self.height_encoders_first_group_2(x_height)
                    #
                    # print(x_height_2.shape)
                    #
                    x_height_3 = self.height_encoders_first_group_3(x_height)
                    #
                    # print(x_height_3.shape)
                    #
                    x_height_4 = self.height_encoders_first_group_4(x_height)
                    #
                    # print(x_height_4.shape)
                    #
                    x_height = x_height_1 + x_height_2 + x_height_3 + x_height_4
                    #
                    # diffY = torch.tensor([x_height_1.size()[2] - x_height_2.size()[2]])
                    # diffX = torch.tensor([y_e.size()[3] - y.size()[3]])
                    #
                    x_width = self.encoders_bottlenecks[i](x_width)
                    #
                    x_width_1 = self.width_encoders_first_group_1(x_width)
                    #
                    # print(x_width_1.shape)
                    #
                    x_width_2 = self.width_encoders_first_group_2(x_width)
                    #
                    # print(x_width_2.shape)
                    #
                    x_width_3 = self.width_encoders_first_group_3(x_width)
                    #
                    # print(x_width_3.shape)
                    #
                    x_width_4 = self.width_encoders_first_group_4(x_width)
                    #
                    # print(x_width_4.shape)
                    #
                    x_width = x_width_1 + x_width_2 + x_width_3 + x_width_4
                    #
                    #
                encoder_height_features.append(x_height)
                #
                encoder_width_features.append(x_width)
                #
                x_a = x_height * (torch.transpose(x_width, 2, 3))
                #
                # print(x_a.shape)
                #
                b, c, h, w = x_a.shape

                if h > w:

                    x_a = torch.reshape(x_a, (b, (2**(i+1))*c, h // (2**(i+1)), w))

                elif h < w:

                    x_a = torch.reshape(x_a, (b, (2**(i+1))*c, h, w // (2**(i+1))))

                else:

                    x_a = x_a

                x_main = torch.sigmoid(x_a) * x_main + x_main

                if self.side_output_mode is True:
                    #
                    avg_rep = torch.mean(x_a, dim=1, keepdim=True)
                    #
                    side_outputs.append(avg_rep)

                encoder_features.append(x_main)

            else:

                encoder_features.append(x_main)

        if self.mode == 'low_rank_attn':

            x_main = self.bridge(x_main)

        # =================================================================================
        # =================================================================================
        # Decoders
        # =================================================================================
        # =================================================================================
        for i in range(self.depth):
            #
            if self.mode == 'relaynet' or self.mode == 'low_rank_attn':
                #
                x_main = self.decoders_unpooling[i](x_main, encoder_indices[self.depth - i], encoder_pool_shapes[self.depth - i])
                #
                x_main = self.decoders[i](torch.cat([x_main, encoder_features[-(i + 2)]], dim=1))
            #
            if self.mode == 'low_rank_attn':
                #
                x_height = x_height + encoder_height_features[-i - 1]
                #
                x_width = x_width + encoder_width_features[-i - 1]
                #
                x_height = self.upsample(x_height)
                #
                x_width = self.upsample(x_width)
                #
                x_height_1 = self.height_decoders_group_1[i](x_height)
                #
                # print(x_height_1.shape)
                #
                x_height_2 = self.height_decoders_group_2[i](x_height)
                #
                # print(x_height_2.shape)
                #
                x_height_3 = self.height_decoders_group_3[i](x_height)
                #
                # print(x_height_3.shape)
                #
                x_height_4 = self.height_decoders_group_4[i](x_height)
                #
                # print(x_height_4.shape)
                #
                x_height = x_height_1 + x_height_2 + x_height_3 + x_height_4
                #
                #
                x_width_1 = self.width_decoders_group_1[i](x_width)
                #
                # print(x_width_1.shape)
                #
                x_width_2 = self.width_decoders_group_2[i](x_width)
                #
                # print(x_width_2.shape)
                #
                x_width_3 = self.width_decoders_group_3[i](x_width)
                #
                # print(x_width_3.shape)
                #
                x_width_4 = self.width_decoders_group_4[i](x_width)
                #
                # print(x_width_4.shape)
                #
                x_width = x_width_1 + x_width_2 + x_width_3 + x_width_4
                #
                x_a = x_height * (torch.transpose(x_width, 2, 3))
                #
                b, c, h, w = x_a.shape
                #
                #
                if h > w:
                    #
                    x_a = torch.reshape(x_a, (b, (2**(self.depth - i))*c, h // (2**(self.depth - i)), w))
                    #
                elif h < w:
                    #
                    x_a = torch.reshape(x_a, (b, (2**(self.depth - i))*c, h, w // (2**(self.depth - i))))
                    #
                else:
                    #
                    x_a = x_a
                #
                x_main = torch.sigmoid(x_a) * x_main + x_main
                #
                if self.side_output_mode is True:
                    #
                    avg_rep = torch.mean(x_a, dim=1, keepdim=True)
                    #
                    side_outputs.append(avg_rep)
                #
        if self.mode == 'low_rank_attn' or self.mode == 'relaynet':

            x_main = self.decoder_last_conv(torch.cat([self.upsample(x_main), x_], dim=1))
        #
        output = self.classification_layer(x_main)
        #
        if self.side_output_mode is True and self.mode == 'low_rank_attn':
            #
            return output, side_outputs
        else:
            #
            return output
