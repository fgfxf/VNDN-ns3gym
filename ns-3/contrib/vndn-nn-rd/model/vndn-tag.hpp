/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */
/**
 * \file vndn-tag.hpp
 * \brief 车联网 NDN 自定义数据包标签（兼容性头文件）。
 *
 * VndnTag 的核心实现（含 wire 编解码）已提升至 ndn-cxx 的 lp 层，
 * 位于 ndn-cxx/lp/vndn-tag.hpp，与 GeoTag 并列，以便在 NDNLPv2 中
 * 作为 LP field 进行序列化与反序列化。
 *
 * 本文件提供 vanet::lp::VndnTag 作为 ndn::lp::VndnTag 的别名，
 * 使 contrib 中的应用代码无需修改即可继续使用。
 */

#ifndef VNDN_TAG_HPP
#define VNDN_TAG_HPP

#include "ndn-cxx/lp/vndn-tag.hpp"

namespace vanet {
namespace lp {

/// \brief ndn::lp::VndnTag 的兼容别名，供 contrib 应用代码使用。
using VndnTag = ndn::lp::VndnTag;

} // namespace lp
} // namespace vanet

#endif // VNDN_TAG_HPP
