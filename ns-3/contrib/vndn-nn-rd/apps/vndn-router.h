/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */
#ifndef VNDN_ROUTER_H
#define VNDN_ROUTER_H

#include <ndn-cxx/face.hpp>
#include <ndn-cxx/interest.hpp>

namespace vanet {

/**
 * \brief 最基础的 VNDN 路由器应用。
 *
 * 当前仅注册根前缀并打印收到的 Interest，不发送 Data，也不主动发送 Interest。
 */
class VndnRouter
{
public:
  VndnRouter ();

  void
  Start ();

  void
  Stop ();

private:
  void
  ProcessInterest (const ndn::Interest &interest);

private:
  ndn::Face m_face;
  bool m_active = false;
};

} // namespace vanet

#endif // VNDN_ROUTER_H
