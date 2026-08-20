import configuration
import logs
import movement_service
import ground_station_service
import camera_service

movement_service.init()
ground_station_service.service.start()
